with open('static/index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# find module-curvas
start_curvas = -1
end_curvas = -1
for i, line in enumerate(lines):
    if 'id="module-curvas"' in line:
        start_curvas = i - 1 # include the comment
    if '<!-- MODULE: AJUSTES -->' in line and start_curvas != -1:
        end_curvas = i
        break

curvas_lines = lines[start_curvas:end_curvas]

# find module-ajustes end
end_ajustes = -1
for i, line in enumerate(lines):
    if 'id="module-ajustes"' in line:
        pass
    if '</section>' in line and i > 1850:
        if 'id="module-ajustes"' in ''.join(lines[i-20:i]):
            end_ajustes = i + 1
            break

# Construct new lines
new_lines = []
for i, line in enumerate(lines):
    if i == start_curvas - 1: # Line 808
        new_lines.append('          </div>\n')
    elif i >= start_curvas and i < end_curvas:
        pass # skip curvas
    elif i == end_ajustes:
        new_lines.append('\n')
        new_lines.extend(curvas_lines)
        new_lines.append(line)
    else:
        # replace the misleading AJUSTES comment
        if i == end_curvas and '<!-- MODULE: AJUSTES -->' in line:
            new_lines.append('          <!-- MODULE: DISTRIBUCION (RESULTADOS) -->\n')
        else:
            new_lines.append(line)

with open('static/index.html', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('Moved module-curvas to the end successfully.')
