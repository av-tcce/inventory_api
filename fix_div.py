with open('static/index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    # If the next line is the empty state and this line is just a </div>
    if i < len(lines) - 2 and 'id="curve-empty-state"' in lines[i+2]:
        if '</div>' in line and line.strip() == '</div>':
            print(f"Removing extra </div> at line {i+1}")
            continue # skip this line
    new_lines.append(line)

with open('static/index.html', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
