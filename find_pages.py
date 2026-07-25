with open('static/index.html', 'r', encoding='utf-8') as f:
    for i, line in enumerate(f):
        if 'class="page-content"' in line:
            print(f'page-content starts at line {i+1}')
        if 'module-curvas' in line:
            print(f'module-curvas at line {i+1}')
        if 'class="container"' in line:
            print(f'container starts at line {i+1}')
        if 'class="app-layout"' in line:
            print(f'app-layout starts at line {i+1}')
