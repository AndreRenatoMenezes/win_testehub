# Avisos de terceiros

## Componentes redistribuídos neste repositório

### DiskSpd 2.2.0

- **Arquivo:** `Testes/2_disco/diskspd.exe`
- **Origem:** <https://github.com/microsoft/diskspd>
- **Licença:** MIT

```text
The MIT License (MIT)

Copyright (c) 2014 Microsoft

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Componentes obtidos à parte (não redistribuídos)

| Componente | Usado em | Como é obtido |
|------------|----------|---------------|
| Microsoft Edge WebDriver (`msedgedriver.exe`) | Módulos 1, 3 e 3.1 | Selenium Manager, automaticamente, ou [download oficial](https://developer.microsoft.com/microsoft-edge/tools/webdriver/) |
| Python 3.12 | Todos os testes `.py` | Setup `4_install_python` (python.org) |
| Pacotes Python (psutil, selenium, pandas, pyautogui, pyperclip, pynput, requests, speedtest-cli) | Testes `.py` | Setup `5_install_py_dependencies` (PyPI) |
| Windows ADK, CrystalDiskMark e CrystalDiskInfo | Preparação da máquina (o Windows Performance Toolkit dos Módulos 1 e 5 faz parte do ADK) | Setup `3_softwares_msStore` (winget) |
