# Protocol tables

Lookup material: every message the codec knows, and every nomenclature code it can
resolve. Both pages are **generated at build time** from the package's own data —
`MessageLists`/`MessageParameters` for the messages, `IntellivueDataFiles/*.txt` for
the codes — so they describe what the installed version actually does, not what it did
when someone last edited a Markdown file.

For what the codes *mean*, see {doc}`../concepts/model` and
{doc}`../concepts/messages`.

```{toctree}
:maxdepth: 2

messages
nomenclature
```
