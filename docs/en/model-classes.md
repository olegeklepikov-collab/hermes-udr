# Model classes

[Home](../../README.md) · [Русский](../ru/model-classes.md)

A class is an operator-owned route name, not a fixed model or quality certification. Change its mapping in the selected Hermes profile without rebuilding the plugin. Replace the example values with identifiers supported by your Hermes configuration.

```yaml
research:
  default_model_class: balanced
  model_classes:
    balanced:
      provider: your-provider-id
      model: your-current-model-id
      reasoning: medium
    advanced:
      provider: another-provider-id
      model: your-current-reasoning-model-id
      reasoning: high
```

Standalone `run_research.py` accepts `--model-class advanced`; `HERMES_RESEARCH_MODEL_CLASS` is also supported. Without a class table, the explicit Hermes model configuration is used. Invalid settings do not silently switch vendors. Reasoning levels must be supported by the selected model.

In Foundation mode, `run_in_host` uses an already-created agent: the existing host resolves its class before constructing that agent. The plugin does not replace its model. API/OAuth authentication and endpoints remain Hermes settings; credentials do not belong in research artifacts or published configuration.
