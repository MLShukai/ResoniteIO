# spec-test-author memory index

- [Locomotion field-rename test scope](locomotion_field_rename_scope.md) — どのテストが proto field rename/renumber に追従し、どれが追従しないか
- [ContextMenu modality](project_context_menu_modality.md) — radial T-key menu unary RPC modality, mirrored on Display; Service exception→status map and SessionHostHarness usage
- [Dash screens modality](project_dash_screens_modality.md) — ListScreens/SetScreen screen enumerate+navigate; both-empty→InvalidArgument, disabled-screen detail, ApiContract Ordinal placement
- [Kestrel ServiceHost base](feedback_kestrel_servicehost_base.md) — 単機能 gRPC round-trip host は Common/KestrelServiceHost<TService> を継承し固有部分(label+bridge DI)だけ書く
- [uds_server fixture](feedback_uds_server_fixture.md) — grpclib end-to-end client test の共有 conftest factory; IServable typing gotcha; migrate 可否
- [E2E harness collection](feedback_e2e_harness_collection.md) — verify new tests/e2e/<modality>.py via --collect-only, never bare pytest (hangs); naming/screenshot conventions
