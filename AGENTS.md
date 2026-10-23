# Working in GAgent

Read [CONTRIBUTING.md](CONTRIBUTING.md), then the guide relevant to the change.
[docs/README.md](docs/README.md) is the documentation index.

- Follow the user's authorized scope. Repository visibility, releases, credentials
  and live device/service actions are separate from editing source.
- Inspect current source and CI before making claims about behavior or support.
  Preserve work and data owned by the user or other contributors.
- Prefer the smallest coherent fix at the owning adapter. Keep GA core changes
  limited to reproduced failures that cannot be resolved at the boundary.
- Identify variable inputs and invariants. Prefer pure parsing, validation and
  policy functions; make network, files, clocks and Android effects explicit.
- Do not hardcode a device size, orientation, OEM layout or an app-specific workaround
  for a general interface defect. Re-observe and verify state after actions.
- WeChat uses the visual-only route; do not introduce node-tree, internal API or
  target-app CDP access. Test control may use only GAgent's own WebView.
- Use synthetic fixtures. Never commit keys, personal configuration, screenshots,
  account data, signing material, production logs or old private repository history.
- Run relevant existing checks from [Testing](docs/TESTING.md). Do not create
  artificial tests for a prose-only edit. Distinguish passed, failed and untested.
- Keep README.md and README.zh-CN.md consistent for capabilities and limitations.
  Keep translated UI strings and HTML fallback text consistent.
- Do not install new dependencies, clear device data or run live model calls
  merely to make a documentation check pass.
- Report the actual change, validation and remaining limits. Do not describe a
  source audit, build, self-review or simulated device as stronger evidence than it is.
