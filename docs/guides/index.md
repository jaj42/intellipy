# Guides

Task-oriented walkthroughs. Read {doc}`install` and {doc}`quickstart` first; the rest
stand alone.

```{toctree}
:maxdepth: 2

install
quickstart
enumeration
record
realtime
demographics
```

:::{admonition} What you need
:class: note

A monitor is required for everything except {doc}`install` and the offline paths noted
in {doc}`enumeration` and {doc}`realtime` — the enumeration decoder runs against a
packet capture, and the real-time example has a `--simulate` mode. If you are working
without hardware, those two are where to start.
:::
