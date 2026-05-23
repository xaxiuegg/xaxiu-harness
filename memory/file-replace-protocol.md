# FILE/REPLACE protocol — engine output contract

When a worker dispatches an edit task, the engine MUST respond using
the FILE/REPLACE protocol below.  No prose, no markdown wrappers
around the protocol blocks, no inline explanations.

## Exact shape

```
FILE: relative/path/to/file.ext
<<<<<<< SEARCH
(exact existing text to replace; leave empty to create file or append)
=======
(replacement text)
>>>>>>> REPLACE
```

## Rules

1. **SEARCH text must match the file** — byte-exact preferred.  The
   harness has CRLF-tolerance (W5-J) and whitespace-fuzzy (W5-R) so
   minor variation works, but **truly different content fails**.
2. **Empty SEARCH = append idiom**: on an existing file, an empty
   SEARCH block treats REPLACE as content to append at end.
3. **New file**: target file doesn't exist → harness creates it with
   REPLACE content as the body.  SEARCH can be empty.
4. **No code-fence wrapper**: do NOT wrap the FILE/REPLACE block in
   ``` fences.  The parser will not strip them.
5. **No prose**: do NOT emit "Here's the edit:" or "The file should
   now be:" before/between/after blocks.
6. **Multiple blocks OK**: one block per file edit; the parser
   iterates all matches.

## Anti-patterns (what NOT to do)

### ❌ Wrapped in markdown
````
```markdown
FILE: foo.md
<<<<<<< SEARCH
...
```
````

### ❌ Prose explanation
> Here's the updated file:
> ```
> FILE: foo.md
> ...

### ❌ Whole-file rewrite in a markdown block
```markdown
# New foo.md

content
```

### ❌ Diff-style output
```diff
--- a/foo.md
+++ b/foo.md
@@ -1 +1 @@
-old
+new
```

## Why this protocol

The harness's `_apply_file_edits` parser specifically looks for the
`FILE:`, `<<<<<<< SEARCH`, `=======`, `>>>>>>> REPLACE` tokens.
Anything else returns 0 edits, fires the W4-A silent_no_op guard,
and (if `--fallback-engine` is set) retries with the fallback.

If you find yourself wanting to output a whole rewritten file, use:
```
FILE: relative/path
<<<<<<< SEARCH
=======
(full new file content)
>>>>>>> REPLACE
```
(empty SEARCH = "create file" or "append" — on an existing file
this becomes append-not-replace, so use carefully.)
