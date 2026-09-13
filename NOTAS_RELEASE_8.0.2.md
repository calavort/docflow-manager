### Arquivos: arrastar e última pasta

- **Arrastar e soltar corrigido**: a captura nativa agora fica ligada somente ao documento inteiro, seguindo o fluxo oficial do pywebview 6.2.1. O backend aceita `dataTransfer` e `domTransfer` e lê `pywebviewFullPath`.
- **Última pasta de entrada lembrada**: ao selecionar arquivos, o programa grava a pasta utilizada em `%LOCALAPPDATA%\DocFlow Manager\settings.json`. Na próxima seleção, inclusive após reiniciar o programa, o diálogo abre nessa pasta.
- O fallback do seletor do próprio pywebview também recebe a mesma pasta inicial.
