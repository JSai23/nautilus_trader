if .type == "assistant" then
  (.message.content[]? |
    if .type == "text" then .text
    elif .type == "tool_use" then
      if .name == "Read" then "→ Read \(.input.file_path)\n"
      elif .name == "Write" then "→ Write \(.input.file_path)\n"
      elif .name == "Edit" then "→ Edit \(.input.file_path)\n"
      elif .name == "Bash" then "→ Bash: \(.input.command | .[0:120])\n"
      elif .name == "Grep" then "→ Grep \(.input.pattern) \(.input.path // "")\n"
      elif .name == "Glob" then "→ Glob \(.input.pattern)\n"
      else "→ \(.name)\n"
      end
    else empty end) // empty
elif .type == "result" then
  "\n" + (.result // "") + "\n"
else empty end
