using System;
using System.Reflection;
using System.Threading;
using FrooxEngine;
using HarmonyLib;
using ResoniteIO.Core;
using ResoniteIO.Core.Logging;
using ResoniteIO.Core.Speaker;

namespace ResoniteIO.Bridge;

/// <summary>
/// <see cref="ISpeakerBridge"/> の FrooxEngine 実装。
/// <see cref="AudioOutputDriver.AudioFrameRendered(float[], double)"/> を HarmonyLib
/// Postfix patch で tap し、engine final mix (world + voice + UI) を Core 側
/// <see cref="PushedAudioFrameSpeakerBridge"/> へ push する。
/// </summary>
/// <remarks>
/// <para>
/// 設計判断 (plan §設計判断):
/// </para>
/// <list type="bullet">
/// <item>
/// <description>
/// <c>RenderAudio</c> プロパティ (Action?) は event ではなく <c>AudioSystem</c> が
/// direct assign で使用しているため、上書き subscribe すると engine が壊れる。
/// よって HarmonyLib Postfix を一本採用する。
/// </description>
/// </item>
/// <item>
/// <description>
/// 対象 driver は <see cref="AudioSystem.PrimaryOutput"/>.<c>Device</c> (world main mix)
/// のみ。<c>StreamingOutput</c> (camera audio) は対象外。
/// </description>
/// </item>
/// <item>
/// <description>
/// Patch target は <see cref="AudioOutputDriver"/> 基底メソッドにあてる。派生
/// (<c>CSCoreAudioOutputDriver</c> 等) でも base method を継承するため effective。
/// 但し OS / 音量設定変更で <c>PrimaryOutput.Device</c> が swap される (decompile:
/// AudioSystem.OnAudioOutputDeviceChanged) ため、<see cref="AudioSystem.DefaultAudioOutputChanged"/>
/// を subscribe して <see cref="_targetDriver"/> を更新する。
/// </description>
/// </item>
/// <item>
/// <description>
/// Postfix は static method (Harmony 制約) なので、mod 全体で 1 bridge instance
/// が前提という設計を <see cref="_singleton"/> static field で表現する。Plugin
/// (<see cref="ResoniteIOPlugin"/>) が同時に 2 つ作る経路は無いが、defensive に
/// 二重生成で例外を投げる。
/// </description>
/// </item>
/// </list>
/// <para>
/// thread safety: Harmony Postfix は WASAPI audio callback スレッドから呼ばれる。
/// <see cref="_inner"/> (<see cref="PushedAudioFrameSpeakerBridge"/>) は内部
/// <c>Channel</c> がスレッドセーフ。<see cref="_targetDriver"/> の参照書換は
/// volatile read/write で十分 (古い参照を 1 frame だけ拾っても害無し、最悪
/// 直前まで使っていた driver のフレームが 1 つ多く流れるだけ)。Postfix 内では
/// log を出さない (毎 21ms 呼ばれる hot path)。
/// </para>
/// </remarks>
internal sealed class FrooxEngineSpeakerBridge : ISpeakerBridge
{
    private const string HarmonyId = "net.mlshukai.resonite-io.speaker";

    /// <summary>
    /// Harmony Postfix から dispatch するために単一 instance を保持する。
    /// 二重 ctor は <see cref="InvalidOperationException"/>。
    /// </summary>
    private static FrooxEngineSpeakerBridge? _singleton;

    private readonly PushedAudioFrameSpeakerBridge _inner = new(
        PushedAudioFrameSpeakerBridge.DefaultCapacity
    );
    private readonly Harmony _harmony;
    private readonly AudioSystem? _audioSystem;
    private readonly ILogSink _log;

    // Postfix は static method 制約のため _singleton 経由でこの field を読む。
    // volatile な 1 word reference 書換は atomic、Postfix は ReferenceEquals で
    // フィルタするだけなので tearing で誤判定しても害無し。
    private volatile AudioOutputDriver? _targetDriver;
    private bool _patched;

    private int _disposed;

    public FrooxEngineSpeakerBridge(Engine engine, ILogSink log)
    {
        ArgumentNullException.ThrowIfNull(engine);
        ArgumentNullException.ThrowIfNull(log);

        if (Interlocked.CompareExchange(ref _singleton, this, null) is not null)
        {
            throw new InvalidOperationException(
                "FrooxEngineSpeakerBridge: another instance is already alive."
            );
        }

        _log = log;
        _audioSystem = engine.AudioSystem;
        _harmony = new Harmony(HarmonyId);

        if (_audioSystem is null)
        {
            _log.LogWarning(
                "Speaker Bridge: Engine.AudioSystem is null at OnEngineReady; "
                    + "speaker stream will remain empty until engine reinitializes."
            );
            return;
        }

        // engine 側で device 切替が起きたら新 driver に re-attach する。
        _audioSystem.DefaultAudioOutputChanged += OnDefaultAudioOutputChanged;

        // 初期 snapshot: AudioSystem は OnEngineReady の前段で initialize 済み
        // (Engine.InitializeAudioSystem) なので、ここで Device が見えているはず。
        // 見えなくても OnDefaultAudioOutputChanged が後から発火する。
        TryAttachInitial(_audioSystem);
    }

    private void TryAttachInitial(AudioSystem audioSystem)
    {
        var initialDriver = audioSystem.PrimaryOutput?.Device as AudioOutputDriver;
        if (initialDriver is null)
        {
            _log.LogInfo(
                "Speaker Bridge: PrimaryOutput.Device not ready at construction; "
                    + "deferring until DefaultAudioOutputChanged fires."
            );
            EnsurePatched();
            return;
        }

        _targetDriver = initialDriver;
        EnsurePatched();
        _log.LogInfo(
            $"Speaker Bridge: attached to AudioOutputDriver '{initialDriver.Name}' "
                + $"(device='{initialDriver.DeviceID}', sampleRate={initialDriver.OutputSampleRate})"
        );
    }

    private void OnDefaultAudioOutputChanged(AudioOutputDriver newDriver)
    {
        if (Volatile.Read(ref _disposed) != 0)
        {
            return;
        }

        // Patch は AudioOutputDriver 基底にあてるため、driver 個体が変わっても
        // 再 patch は不要。target 参照だけ差し替える。
        _targetDriver = newDriver;
        if (newDriver is null)
        {
            _log.LogInfo("Speaker Bridge: default audio output cleared.");
            return;
        }

        EnsurePatched();
        _log.LogInfo(
            $"Speaker Bridge: re-attached to AudioOutputDriver '{newDriver.Name}' "
                + $"(device='{newDriver.DeviceID}')"
        );
    }

    private void EnsurePatched()
    {
        if (_patched)
        {
            return;
        }

        var original = AccessTools.Method(
            typeof(AudioOutputDriver),
            nameof(AudioOutputDriver.AudioFrameRendered),
            [typeof(float[]), typeof(double)]
        );
        if (original is null)
        {
            _log.LogError(
                "Speaker Bridge: AudioOutputDriver.AudioFrameRendered method not found; "
                    + "speaker tap unavailable."
            );
            return;
        }

        var postfix = new HarmonyMethod(
            typeof(FrooxEngineSpeakerBridge).GetMethod(
                nameof(OnAudioFrameRenderedPostfix),
                BindingFlags.NonPublic | BindingFlags.Static
            )
        );

        try
        {
            _harmony.Patch(original, postfix: postfix);
            _patched = true;
            _log.LogInfo(
                "Speaker Bridge: HarmonyLib Postfix attached to "
                    + "AudioOutputDriver.AudioFrameRendered"
            );
        }
        catch (Exception ex)
        {
            _log.LogError($"Speaker Bridge: failed to apply Harmony patch: {ex}");
        }
    }

    /// <summary>
    /// HarmonyLib によって <see cref="AudioOutputDriver.AudioFrameRendered(float[], double)"/>
    /// の直後に呼ばれる static postfix。WASAPI audio thread から実行される。
    /// </summary>
    /// <remarks>
    /// 速度クリティカル: 毎 ~21 ms (1024 sample @ 48 kHz) で呼ばれるため allocation /
    /// log を最小化する。アロケーションは <see cref="PushedAudioFrameSpeakerBridge.Push"/>
    /// 内部の defensive byte[] copy 1 度のみ (engine が float[] を callback 復帰後に
    /// reuse しうるため避けられない)。
    /// </remarks>
    private static void OnAudioFrameRenderedPostfix(
        AudioOutputDriver __instance,
        float[] buffer,
        double dspTime
    )
    {
        // dspTime は使わない (proto の unix_nanos は外部時計 = UnixNanosClock で
        // stamp する。dsp は engine 内部 clock で client 側の壁時計同期に使えない)。
        _ = dspTime;

        var bridge = _singleton;
        if (bridge is null)
        {
            return;
        }
        if (!ReferenceEquals(__instance, bridge._targetDriver))
        {
            // 他 driver instance (例: StreamingOutput, 旧 default driver) の callback。
            return;
        }
        if (buffer is null || buffer.Length == 0)
        {
            return;
        }

        try
        {
            bridge._inner.Push(buffer, UnixNanosClock.Now());
        }
        catch (Exception)
        {
            // WASAPI thread に例外を逃がすと engine が落ちる可能性がある。
            // log も Postfix の hot path では呼ばない (BepInExLogSink は内部で
            // lock を取る可能性があり audio glitch の原因になる)。
            // Push の唯一の throw 経路は buffer.Length が奇数の場合だが、
            // PrimaryOutput は stereo 固定なので実機では発火しない想定。
        }
    }

    /// <inheritdoc/>
    public System.Collections.Generic.IAsyncEnumerable<AudioFrame> StreamFramesAsync(
        CancellationToken ct
    ) => _inner.StreamFramesAsync(ct);

    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }

        try
        {
            if (_audioSystem is not null)
            {
                _audioSystem.DefaultAudioOutputChanged -= OnDefaultAudioOutputChanged;
            }
        }
        catch (Exception ex)
        {
            _log.LogWarning(
                $"Speaker Bridge: DefaultAudioOutputChanged unsubscribe threw: {ex.Message}"
            );
        }

        if (_patched)
        {
            try
            {
                _harmony.UnpatchSelf();
            }
            catch (Exception ex)
            {
                _log.LogWarning($"Speaker Bridge: Harmony.UnpatchSelf threw: {ex.Message}");
            }
            _patched = false;
        }

        _targetDriver = null;

        // Postfix は static でこのフィールドを読むため、_inner Dispose より先に
        // singleton を外して新規 push を遮断する。order: singleton clear → inner dispose。
        Interlocked.CompareExchange(ref _singleton, null, this);

        _inner.Dispose();
        _log.LogInfo("Speaker Bridge disposed: harmony unpatched, channel completed");
    }
}
