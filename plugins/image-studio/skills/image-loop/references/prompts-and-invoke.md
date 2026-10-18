# Prompts and invocation

Read by [image-loop](../SKILL.md) only when writing a generation or edit prompt, or invoking the loop on another host.

## Invoke

- Claude Code: `/image-loop [brief]` (a plugin install shows it with the plugin's prefix), or describe the task and let the skill load.
- Codex: `$image-loop [brief]` or select through `/skills` where supported. Do not claim a custom `/image-loop` command is registered on every host.

## Prompt pattern

Use result → subject/action → composition → medium/style → visible details → constraints for generation. For edits, use source → target/property → requested delta → protected details → success checks. Specify roles for multiple references. Keep prompts as short as the job permits; syntax and length are not quality guarantees.

The public prompt library and example results are in the repository's `prompts/` and `examples/` folders (not included in a plain skills install). General prompting principles were informed by the [OpenAI image prompting guide](https://developers.openai.com/api/docs/guides/image-prompting); the numbered controls, review contract, and bounded controller are this package's implementation.
