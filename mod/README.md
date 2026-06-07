# ResoniteIO

**ResoniteIO** turns [Resonite](https://resonite.com/) into a runtime environment for AI
agents. This mod runs inside the Resonite client and exposes vision, audio, movement, and UI
control to an external agent over gRPC on a Unix Domain Socket. You drive it from the
companion [`resonite-io`](https://pypi.org/project/resonite-io/) Python client (imported as `resoio`).

## Requirements

- The supporting plugins (BepisLoader, BepInExResoniteShim, BepisResoniteWrapper,
  RenderiteHook, InterprocessLib) are resolved automatically as dependencies — install this
  package through a mod manager such as [Gale](https://github.com/Kesomannen/gale).

- **Set the Steam launch option** for Resonite (required):

  ```text
  WINEDLLOVERRIDES="winhttp=n,b" %command%
  ```

  Without it the renderer-side plugin never loads and camera capture will not work.

## Usage

Install the [`resonite-io`](https://pypi.org/project/resonite-io/) Python client (`pip install resonite-io`)
and connect from your agent code. See the full documentation for setup, the modality matrix,
and the API reference:

- **Documentation:** <https://mlshukai.github.io/ResoniteIO/>
- **Source:** <https://github.com/MLShukai/ResoniteIO>

## License

[MIT](https://github.com/MLShukai/ResoniteIO/blob/main/LICENSE)
