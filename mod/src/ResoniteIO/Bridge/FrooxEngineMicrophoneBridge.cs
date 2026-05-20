using System;
using System.Runtime.InteropServices;
using Elements.Assets;
using FrooxEngine;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Microphone;

namespace ResoniteIO.Bridge;

/// <summary>
/// <see cref="IMicrophoneBridge"/> の FrooxEngine 実装。
/// </summary>
/// <remarks>
/// <para>
/// アーキテクチャ: Python から push された float32 mono samples を Bridge 内部
/// ring buffer に append し、engine update tick 上で <c>WriteSamples&lt;MonoSample&gt;</c>
/// 経由で <see cref="ResoniteIOAudioInput"/> (= <see cref="AudioInput"/> 派生) に流す。
/// <see cref="ResoniteIOAudioInput"/> は <see cref="AudioSystem.RegisterAudioInput"/>
/// で engine に登録され、Resonite UI で default Audio Input に選ばれれば
/// <c>UserAudioStream&lt;MonoSample&gt;</c> 経由で他ユーザーに voice として broadcast
/// される (Opus encode は engine 側自動)。
/// </para>
/// <para>
/// thread safety: <see cref="SubmitFrame"/> は任意スレッドから呼ばれる
/// (gRPC server thread)。ring buffer は内部 lock 保護。<see cref="TickStep"/> は
/// <c>World.RunInUpdates(0, ...)</c> で engine update thread に dispatch
/// する self-rescheduling repeater (Locomotion Bridge と同 pattern)。
/// </para>
/// <para>
/// Dispose ordering: AudioSystem に <c>UnregisterAudioInput</c> API は存在しない
/// (decompile 確認: AudioInputs リストへの Add のみで Remove 経路無し)。本クラスは
/// <see cref="AudioSystem.AudioInputs"/> リストから直接 Remove する best-effort 経路を
/// 採るが、private <c>_audioInputDeviceIDs</c> HashSet には残るため engine 再 register
/// 時に DeviceID 重複 warning が出る可能性がある (mod 再 load 時のみ、機能影響なし)。
/// </para>
/// </remarks>
internal sealed class FrooxEngineMicrophoneBridge : IMicrophoneBridge, IDisposable
{
    private readonly WorldManager _worldManager;
    private readonly AudioSystem? _audioSystem;
    private readonly ResoniteIOAudioInput? _audioInput;
    private readonly ILogSink _log;

    private readonly object _lock = new();
    private World? _cachedWorld;
    private World? _repeaterWorld;
    private bool _repeaterRunning;

    // WriteSamples<MonoSample> の interpolation state。engine thread (TickStep)
    // からのみ touch するため lock 不要。
    private double _position;
    private MonoSample _lastSample;

    private volatile bool _disposed;

    public FrooxEngineMicrophoneBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        _worldManager = engine.WorldManager;
        _log = log;
        _audioSystem = engine.AudioSystem;

        if (_audioSystem is null)
        {
            // Speaker Bridge と同じ defensive 経路。AudioSystem 未初期化時は virtual
            // mic を登録できないため、Bridge は no-op に縮退する (SubmitFrame は
            // 空 ring buffer に書き込むだけになる)。
            _log.LogWarning(
                "Microphone Bridge: Engine.AudioSystem is null at construction; "
                    + "virtual mic registration skipped."
            );
            return;
        }

        _audioInput = new ResoniteIOAudioInput(engine);

        try
        {
            _audioSystem.RegisterAudioInput(_audioInput);
            _log.LogInfo(
                $"Microphone Bridge: registered virtual AudioInput '{_audioInput.Name}' "
                    + $"(deviceId='{_audioInput.DeviceID}', sampleRate={MicrophoneFrame.SampleRate}Hz, mono)"
            );
        }
        catch (Exception ex)
        {
            _log.LogError($"Microphone Bridge: RegisterAudioInput threw: {ex}");
            _audioInput = null;
            return;
        }

        // Locomotion と同じ initial-snapshot + WorldFocused subscription pattern。
        // WorldFocused は新規 focus でしか発火しないため、subscribe 前の snapshot で
        // 起動時の窓を埋める。
        var initial = _worldManager.FocusedWorld;
        _cachedWorld = initial;
        _worldManager.WorldFocused += OnWorldFocused;

        if (initial is not null && !initial.IsDisposed)
        {
            EnsureRepeaterStarted(initial);
        }
    }

    /// <inheritdoc/>
    public void SubmitFrame(MicrophoneFrame frame)
    {
        if (_disposed || _audioInput is null)
        {
            return;
        }

        var samples = frame.Samples;
        if (samples.Length == 0 || frame.SampleCount == 0)
        {
            return;
        }

        // SampleCount は Service 側で bytes 長から再計算済み (proto stamp 不信用)。
        // 念のため out-of-range をクランプする (defensive)。
        var count = Math.Min(frame.SampleCount, samples.Length);
        _audioInput.AppendSamples(samples.AsSpan(0, count));

        // WorldFocused 前 / repeater 未起動状態で SubmitFrame が来るケースを救う。
        World? worldToStart;
        lock (_lock)
        {
            worldToStart = _repeaterRunning ? null : _cachedWorld;
        }
        if (worldToStart is not null && !worldToStart.IsDisposed)
        {
            EnsureRepeaterStarted(worldToStart);
        }
    }

    /// <inheritdoc/>
    public void NotifyDisconnect(MicrophoneDisconnectReason reason)
    {
        if (_disposed)
        {
            return;
        }

        // must not throw (IMicrophoneBridge 契約: Service 側で disconnect 通知中に
        // 落ちると lifecycle が壊れる)。AudioInput.Reset 呼び出しの例外は飲み込む。
        try
        {
            _log.LogDebug($"MicrophoneBridge: StreamAudio disconnect reason={reason}");

            switch (reason)
            {
                case MicrophoneDisconnectReason.Graceful:
                    // 正常終了は ring buffer 維持 (engine tick が残り samples を消化、
                    // 再生中の余韻を切らない)。
                    break;
                case MicrophoneDisconnectReason.Cancelled:
                case MicrophoneDisconnectReason.Errored:
                    // RL/ロボティクス safety: client crash 時に古い音が残らないよう
                    // ring buffer を即 clear する。
                    _audioInput?.Reset();
                    break;
            }
        }
        catch (Exception ex)
        {
            // log path も best-effort (ProcessExit 経路では log sink が dead の可能性)。
            try
            {
                _log.LogWarning(
                    $"MicrophoneBridge: NotifyDisconnect swallowed exception: {ex.Message}"
                );
            }
            catch
            {
                // give up silently — 契約上 throw は禁止。
            }
        }
    }

    private void OnWorldFocused(World world)
    {
        if (_disposed)
        {
            return;
        }

        bool restartNeeded = false;
        lock (_lock)
        {
            _cachedWorld = world;
            if (world is not null && !ReferenceEquals(_repeaterWorld, world))
            {
                // 旧 repeater は TickStep 内で bind 不一致を検知して self-terminate。
                _repeaterRunning = false;
                _repeaterWorld = null;
                restartNeeded = true;
            }
        }

        _log.LogDebug($"MicrophoneBridge: world refocused → {world?.Name ?? "<null>"}");

        if (restartNeeded && world is not null && !world.IsDisposed)
        {
            EnsureRepeaterStarted(world);
        }
    }

    private void EnsureRepeaterStarted(World world)
    {
        ArgumentNullException.ThrowIfNull(world);

        bool start = false;
        lock (_lock)
        {
            if (_disposed || _audioInput is null)
            {
                return;
            }

            if (!_repeaterRunning)
            {
                _repeaterWorld = world;
                _repeaterRunning = true;
                start = true;
            }
        }

        if (start)
        {
            try
            {
                world.RunInUpdates(0, TickStep);
            }
            catch (Exception ex)
            {
                _log.LogWarning($"MicrophoneBridge: failed to schedule TickStep: {ex.Message}");
                lock (_lock)
                {
                    _repeaterRunning = false;
                    _repeaterWorld = null;
                }
            }
        }
    }

    /// <summary>
    /// engine update tick 上で 1 度実行され、ring buffer の samples を
    /// <see cref="AudioInput.WriteSamples"/> に流し込んで次 tick へ自己 schedule する。
    /// </summary>
    private void TickStep()
    {
        if (_disposed || _audioInput is null)
        {
            MarkRepeaterStopped(expected: null);
            return;
        }

        World? boundWorld;
        lock (_lock)
        {
            boundWorld = _repeaterWorld;
            if (boundWorld is null)
            {
                _repeaterRunning = false;
                _repeaterWorld = null;
                return;
            }
        }

        if (boundWorld.IsDisposed)
        {
            MarkRepeaterStopped(expected: boundWorld);
            return;
        }

        // 1 tick あたりの取り出し量: 10ms @ 48 kHz = 480 samples。これより少ない場合は
        // 利用可能分だけ書き込む。stackalloc は MaxTickSamples 上限で 1 tick 分。
        _audioInput.DrainAndWrite(ref _position, ref _lastSample);

        if (_disposed || boundWorld.IsDisposed)
        {
            MarkRepeaterStopped(expected: boundWorld);
            return;
        }

        try
        {
            boundWorld.RunInUpdates(0, TickStep);
        }
        catch (Exception ex)
        {
            _log.LogWarning($"MicrophoneBridge: TickStep reschedule failed: {ex.Message}");
            MarkRepeaterStopped(expected: boundWorld);
        }
    }

    private void MarkRepeaterStopped(World? expected)
    {
        lock (_lock)
        {
            if (expected is null || ReferenceEquals(_repeaterWorld, expected))
            {
                _repeaterRunning = false;
                _repeaterWorld = null;
            }
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;

        try
        {
            _worldManager.WorldFocused -= OnWorldFocused;
        }
        catch
        {
            // engine 側が先に破棄されているケースの best-effort。
        }

        lock (_lock)
        {
            _repeaterRunning = false;
            _repeaterWorld = null;
            _cachedWorld = null;
        }

        // AudioSystem に Unregister API が無い (decompile 確認済み)。AudioInputs List
        // から best-effort で除去するのみ。Disconnected() は internal メソッドだが
        // 呼び出し経路としては不要 (UserAudioStream subscriber は世代毎に re-bind)。
        if (_audioInput is not null && _audioSystem is not null)
        {
            try
            {
                _audioSystem.AudioInputs.Remove(_audioInput);
                _audioInput.Reset();
            }
            catch (Exception ex)
            {
                _log.LogWarning($"MicrophoneBridge: AudioInputs.Remove threw: {ex.Message}");
            }
        }

        _log.LogInfo("Microphone Bridge disposed: ring buffer cleared, virtual mic removed");
    }
}

/// <summary>
/// <see cref="AudioInput"/> 派生の virtual capture device。Python から push された
/// float32 mono samples を ring buffer で蓄え、engine tick が
/// <see cref="DrainAndWrite"/> で <c>WriteSamples&lt;MonoSample&gt;</c> 経由 engine に
/// 流し込む。
/// </summary>
/// <remarks>
/// <para>
/// thread safety: <see cref="AppendSamples"/> は任意スレッド safe (内部 lock)。
/// <see cref="DrainAndWrite"/> は engine update thread から **のみ** 呼ぶこと
/// (<c>_position</c> / <c>_lastSample</c> state を読む)。<see cref="Reset"/> は任意。
/// </para>
/// <para>
/// ring buffer 容量は 2 秒分 (= 96000 samples)。容量超過時は古い samples を drop して
/// <see cref="DroppedSamples"/> をカウントする (Python 側が engine tick rate より速く
/// push してきた場合の overflow 防止)。
/// </para>
/// </remarks>
internal sealed class ResoniteIOAudioInput : AudioInput
{
    // 2 秒分 = 96000 samples。実用上 engine tick (~10 ms) は十分速いので overflow
    // しない想定だが、Python 側が一気に流し込んでも吸収できる余裕。
    private const int RingBufferCapacity = MicrophoneFrame.SampleRate * 2;

    // 1 tick あたり 10 ms 相当 = 480 samples。WriteSamples の引数 length 上限。
    private const int MaxTickSamples = MicrophoneFrame.SampleRate / 100;

    private readonly object _bufferLock = new();
    private readonly float[] _buffer = new float[RingBufferCapacity];
    private int _readIndex;
    private int _writeIndex;
    private int _count;
    private long _droppedSamples;

    public ResoniteIOAudioInput(Engine engine)
        : base(
            name: "ResoniteIOMicrophone",
            deviceId: "resoio-mic-virtual",
            input: engine.InputInterface,
            type: AudioInputType.CaptureDevice,
            // 既存ユーザーの mic 設定を壊さないため初期 default は false。
            // Resonite UI で明示的に選択させる (Phase 6 の manual 手順書参照)。
            isDefault: false
        )
    {
        // 48 kHz 固定 (proto / Core IF の定数 MicrophoneFrame.SampleRate と一致)。
        // engine SampleRate と一致するので AudioInput 内の resample 経路は通らない。
        SetSampleRate(MicrophoneFrame.SampleRate);
    }

    /// <summary>累積 drop sample 数 (overflow による)。診断用。</summary>
    public long DroppedSamples
    {
        get
        {
            lock (_bufferLock)
            {
                return _droppedSamples;
            }
        }
    }

    /// <summary>ring buffer に samples を append する。任意スレッド safe。</summary>
    /// <remarks>
    /// overflow 時は古い samples を drop し <see cref="DroppedSamples"/> を加算する。
    /// </remarks>
    public void AppendSamples(ReadOnlySpan<float> samples)
    {
        if (samples.IsEmpty)
        {
            return;
        }

        lock (_bufferLock)
        {
            var incoming = samples.Length;

            // overflow 量: capacity を超えた分だけ古い samples を捨てる。
            var overflow = (_count + incoming) - RingBufferCapacity;
            if (overflow > 0)
            {
                // 一度に入りきらない量 (incoming > capacity) のケース: 末尾のみ保持する。
                if (incoming >= RingBufferCapacity)
                {
                    var keep = RingBufferCapacity;
                    var srcOffset = incoming - keep;
                    _droppedSamples += _count + srcOffset;
                    _count = 0;
                    _readIndex = 0;
                    _writeIndex = 0;
                    samples.Slice(srcOffset, keep).CopyTo(_buffer);
                    _writeIndex = (keep == RingBufferCapacity) ? 0 : keep;
                    _count = keep;
                    return;
                }

                _readIndex = (_readIndex + overflow) % RingBufferCapacity;
                _count -= overflow;
                _droppedSamples += overflow;
            }

            // tail-end 書き込み (折り返し対応)。
            var firstChunk = Math.Min(incoming, RingBufferCapacity - _writeIndex);
            samples.Slice(0, firstChunk).CopyTo(_buffer.AsSpan(_writeIndex));
            if (firstChunk < incoming)
            {
                samples.Slice(firstChunk).CopyTo(_buffer);
            }
            _writeIndex = (_writeIndex + incoming) % RingBufferCapacity;
            _count += incoming;
        }
    }

    /// <summary>ring buffer を完全クリアする。任意スレッド safe。</summary>
    public void Reset()
    {
        lock (_bufferLock)
        {
            _readIndex = 0;
            _writeIndex = 0;
            _count = 0;
        }
    }

    /// <summary>
    /// engine update tick から呼び、利用可能 samples を 1 tick 分 (最大
    /// <see cref="MaxTickSamples"/> = 10 ms) <c>WriteSamples&lt;MonoSample&gt;</c> に
    /// 流す。<paramref name="position"/> / <paramref name="lastSample"/> は
    /// <see cref="AudioInput.WriteSamples"/> 側で書き換えられる interpolation state。
    /// </summary>
    public void DrainAndWrite(ref double position, ref MonoSample lastSample)
    {
        Span<float> scratch = stackalloc float[MaxTickSamples];
        int taken;
        lock (_bufferLock)
        {
            taken = Math.Min(_count, MaxTickSamples);
            if (taken == 0)
            {
                return;
            }

            // 折り返し対応で 2 段 copy。
            var firstChunk = Math.Min(taken, RingBufferCapacity - _readIndex);
            _buffer.AsSpan(_readIndex, firstChunk).CopyTo(scratch);
            if (firstChunk < taken)
            {
                _buffer.AsSpan(0, taken - firstChunk).CopyTo(scratch.Slice(firstChunk));
            }
            _readIndex = (_readIndex + taken) % RingBufferCapacity;
            _count -= taken;
        }

        // float == MonoSample (1 field readonly struct) の memory layout が一致するため
        // zero-copy で reinterpret できる (decompile の CSCoreAudioInputDriver が
        // buffer.AsAudioBuffer<MonoSample>() で同じことをしている)。
        var monoSpan = MemoryMarshal.Cast<float, MonoSample>(scratch.Slice(0, taken));
        WriteSamples(monoSpan, ref position, ref lastSample);
    }
}
