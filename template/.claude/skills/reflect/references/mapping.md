# Mapping: signals → files

Section names follow the structure `/setup` writes. If the owner's files use other headings, map to the closest one.

## persona.md

### 3. Communication style
| Signal | Example | Type |
|---|---|---|
| Length preference changes | "too long", "expand", "one sentence" | UPDATE |
| Format preference changes | "no bullet list", "as a table", "in points" | UPDATE |

### 4. Values and rules
| Signal | Example | Type |
|---|---|---|
| New working principle | "always X before Y", "never do X" | ADD |
| Changed approach | "actually Z is better than Y" | REPLACE |

### 5. Daily work
| Signal | Example | Type |
|---|---|---|
| New working hours or rhythm | "I start at 7 now" | UPDATE |
| New tool used daily | "I moved my notes to X" | ADD |
| New recurring pattern | "I always do X after Y" | ADD |

### 6. Blockers and tensions
| Signal | Example | Type |
|---|---|---|
| New blocker named | "lately I keep postponing X" | ADD |

### 7. Notes for the AI → How to talk to me
| Signal | Example | Type |
|---|---|---|
| Correction of AI behaviour | "don't ask, just do it", "shorter" | ADD/UPDATE |
| New interaction preference | "save it to a file", "show the diff first" | ADD |
| Answer format preference | "no emojis", "more code" | ADD |

### 7. Notes for the AI → What not to do
| Signal | Example | Type |
|---|---|---|
| Rejected tone | "too coachy", "sounds like AI" | ADD |
| Rejected word or phrase | "don't say X", "use Y instead of X" | ADD |
| Rejected format | "no headings", "no bold" | ADD |

## soul.md

### Character
| Signal | Example | Type |
|---|---|---|
| Directness correction | "too harsh", "loosen up", "be blunter" | UPDATE |
| Pace correction | "you're rushing", "give more context" | UPDATE |
| Humour correction | "don't hold back", "too dry" | UPDATE |

### How I communicate → What I never do
| Signal | Example | Type |
|---|---|---|
| New anti-pattern | "don't open with X", "stop doing Y" | ADD |
| Anti-pattern lifted | "you can say X, that's fine" | REMOVE |

### How I communicate → How I talk
| Signal | Example | Type |
|---|---|---|
| Pattern the owner liked | "I like how you did X, always do that" | ADD |
| Pattern changed | "do Y instead of X" | UPDATE |

### How I solve problems
| Signal | Example | Type |
|---|---|---|
| Options correction | "give me more options", "too many variants" | UPDATE |
| Autonomy correction | "don't ask, do it", "ask before you do it" | UPDATE |
| Handling of blockers | "ask sooner", "try longer on your own" | UPDATE |

### How I work with you
| Signal | Example | Type |
|---|---|---|
| Dynamics correction | "too much of a yes-man", "challenge me more" | UPDATE |
| Adaptation | "don't guess what I want", "read between the lines" | UPDATE |
| New collaboration habit | "from now on do X before Y" | ADD |

### What I dislike / What drives me
| Signal | Example | Type |
|---|---|---|
| New negative trigger | "I hate it when AI does X" | ADD to dislikes |
| New energiser | "I love it when X" | ADD to drives |
| Trigger gone | "that doesn't bother me any more" | REMOVE |

## context.md

| Signal | Example | Type |
|---|---|---|
| New business line, product or channel | "we launched X" | ADD |
| Dropped line, tool or channel | "we no longer use X" | REMOVE (dated) |
| Changed stack | "we moved to X" | UPDATE |
| New project | a new initiative described | ADD (one line; details in projects/) |
| Corrected stable fact | "it's 27 units, not 21" | UPDATE (dated) |

Not for context.md: balances, prices, stock, statuses, anything that changes weekly. Those are checked at the source.

## Examples

**Format correction**
```
Owner: "no, shorter"
Owner: "two sentences max"
```
→ persona.md § 7 How to talk to me — ADD: "Prefers very short answers (2–3 sentences)."

**Rejected phrase**
```
Owner: "don't write 'game-changer', it sounds like AI"
```
→ persona.md § 7 What not to do — ADD: "game-changer (sounds like AI)".

**Business fact**
```
Owner: "we have 650 subscribers now"
```
→ Volatile number: skip. If the owner wants a scale marker, use a range ("several hundred subscribers") in context.md § 1, dated.

**Working habit, repeated**
```
Owner: "always show the diff before editing"
Owner (next session): "diff first"
```
→ persona.md § 7 How to talk to me — ADD: "Before writing to files, show the diff and wait for OK."

**One-off — do not add**
```
Owner: "this time no emojis"
```
→ One-off, not repeated → SKIP.

**AI behaviour correction**
```
Owner: "you're too much of a yes-man, push back"
```
→ soul.md § How I work with you — UPDATE: strengthen calling out weak ideas.

**Autonomy correction, repeated**
```
Owner: "don't ask, just do it"
Owner (later): "do it, don't ask"
```
→ soul.md § How I solve problems — UPDATE: act on known patterns without asking; still ask for anything that needs approval under CLAUDE.md.
