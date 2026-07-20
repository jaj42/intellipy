# `intellipy.IntellivueDataFiles.IntellivueData`

The codec: message construction, message parsing, and the nomenclature tables loaded
from the package's `.txt` data files at construction time.

Most users never touch this directly — {doc}`client` wraps it. Reach for it when you
need a message the client does not send, or want to parse captured bytes yourself:

```python
from intellipy.IntellivueDataFiles.IntellivueData import IntellivueData

codec = IntellivueData()
codec.getMessageType(data)                     # classify raw bytes
message = codec.readData(data)                 # parse them
poll = codec.writeData("MDSExtendedPollActionNUMERIC", {"poll_number": 1})
```

`writeData` takes a template name and a dict of parameter overrides; the template
supplies everything you do not set. {doc}`../protocol/messages` lists them all.

```{eval-rst}
.. automodule:: intellipy.IntellivueDataFiles.IntellivueData
   :members:
   :undoc-members:
   :show-inheritance:
```
