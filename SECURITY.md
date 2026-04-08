# Security Notes

## paper2video runs LLM-generated Python code

The Manim renderer asks an LLM to write Python code, then executes that code in a
subprocess to render each scene. This is intentional — it's how the visuals are generated —
but you should be aware of what it means.

**What we do to limit risk:**

- A static linter (`paper2video.renderers.manim_r.lint_manim_code`) blocks generated code that
  imports anything outside `manim`, uses `MathTex`/`Tex` (which would shell out to LaTeX),
  or matches other known-bad patterns. Code that fails lint never runs — it's sent back to
  the LLM for a fix.
- The Manim CLI is invoked as a separate subprocess via `python -m manim`, not via `exec()`
  in the host process.
- Generated code is written to `out/<run_id>/manim/scene_NNN_work/scene_NNN.py` so you can
  always inspect what ran.

**What we do NOT do:**

- We do **not** sandbox the subprocess. The generated code runs with the same OS permissions
  as the host process. A determined attacker who could influence the LLM's output could in
  principle do anything your user can do.
- We do not currently restrict file system access, network access, or process spawning from
  inside the generated code.

**Recommendations:**

- Treat outputs of `paper2video` like any other AI-generated code: useful, but read the
  generated `.py` files in the run directory if you have any reason to be cautious.
- Run paper2video against sources you trust. The LLM is asked to summarize and visualize the
  source content; an article that itself contains prompt-injection text could in theory steer
  the script-writing or codegen LLM.
- For high-paranoia environments, run the whole pipeline inside a container or VM.

## API key handling

`paper2video` reads `ANTHROPIC_API_KEY` from environment or `.env`. The `.env` file is in
`.gitignore` by default. Don't commit it.

If you accidentally share an API key (in a screenshot, transcript, or commit), rotate it
immediately at https://console.anthropic.com/.

## Reporting a vulnerability

If you find a security issue, please open a private security advisory on GitHub rather than
filing a public issue.
