---
name: netstandard20-polyfills
description: netstandard2.0 で Span<T> / BinaryPrimitives を使うには System.Memory が、HashCode.Combine は無いので手組みが必要
metadata:
  type: feedback
---

`RendererShared` のように netstandard2.0 で net10.0 と net472 双方の consumer に
配る pure library を書く時、以下の BCL polyfill が必要:

- `System.Span<T>` / `System.ReadOnlySpan<T>` / `System.Buffers.Binary.BinaryPrimitives`
  → `PackageReference Include="System.Memory" Version="4.6.x"` (transitive
  に net10.0 / net472 consumer 双方で動く polyfill)
- `System.HashCode.Combine` → **無い**。netstandard2.1+ または .NET Core 2.1+ 必須。
  netstandard2.0 では手組み (`unchecked { hash * 31 ^ field.GetHashCode() }`)

**Why:** netstandard2.0 は .NET Framework 4.6.1+ と Mono 互換性のため BCL surface
が小さい。`Span<T>` / `HashCode` 等は後から ref struct や readonly struct で追加された
API で、netstandard2.0 仕様 freeze 後に来た。`System.Memory` NuGet は ref struct を
runtime polyfill で提供する公式パッケージ。

**How to apply:** Camera v2 の `RendererShared` を含む engine↔renderer 共有
ライブラリで `Span<byte>` ベースの binary serialization を書く時は最初から
`System.Memory` PackageReference を足す。`dotnet build` のエラーメッセージは
"'Span\<>' does not exist" と出るので polyfill 不足を即特定できる。
`HashCode.Combine` が無いことは build error にならず実装時に気付くので、
struct equality を書く時は最初から手組み hash を選ぶ。
