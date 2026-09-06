# DOCFLOW MANAGER — PYTHON V8

## Ajustes da V8

- **Folha dividida em inicial e final**: o campo único `13-23` deu lugar a dois campos (`Folha inicial` e `Folha final`). Ao digitar em um deles, o outro é recalculado **na hora**, usando a quantidade de arquivos da lista (ex.: 10 arquivos + folha final `20` → folha inicial `11`). Adicionar ou remover arquivos recalcula o extremo oposto ao último campo editado.
- **Aviso de tipos diferentes**: quando a lista mistura extensões (ex.: 10 DWG + 1 PDF em *Renomear*) ou contém arquivos que a operação escolhida ignora (*Unir PDF* com DWG, *Unir DWG* com PDF), o rodapé da lista de arquivos troca a contagem por um aviso com ícone laranja (ex.: “A lista mistura tipos de arquivos (9 DWG + 1 PDF)”) e uma confirmação aparece antes de iniciar.
- **Renomear usa o formato majoritário**: com a lista misturada, só o formato mais numeroso é renomeado (10 DWG + 1 PDF renomeia os 10 DWG e mantém o PDF como está), porque o arquivo avulso costuma ser engano na seleção. A faixa de folhas, a prévia e a confirmação já consideram apenas esse grupo.
- **Notificações unificadas**: acabaram os diálogos nativos do navegador ("127.0.0.1 diz") e os toasts (em qualquer posição da janela). Toda mensagem usa um único card central no estilo do programa, sem barra vertical: confirmação com *Cancelar* / *Continuar*, sucesso com *OK* / *Abrir pasta* e falha com uma frase curta e *OK*. Avisos de estado ficam no rodapé da lista de arquivos, junto da contagem.
- **Falhas em linguagem clara**: a mensagem perde o horário do log e um PDF ilegível passa a dizer que o arquivo pode estar danificado ou protegido, em vez do erro técnico da biblioteca.
- **Sucesso só depois da conclusão real**: antes de responder, o programa espera cada arquivo de saída aparecer na listagem da pasta e ficar estável, e avisa o Windows Explorer para atualizar a pasta na hora (`SHChangeNotify`) - era isso que fazia o resultado parecer chegar um ou dois segundos depois do aviso.
- **Ícones das operações redesenhados**: Renomear (documento + caneta), Unir PDF (dois documentos convergindo em uma seta), Separar PDF (documento que se divide em duas saídas) e Unir DWG (duas pranchas sobrepostas com selo), todos no mesmo traço de 1,65 px e legíveis a 21 px.
- **"Incluir revisão" passou a valer para o padrão automático**: antes a opção só afetava padrões digitados manualmente e a prévia continuava com `Rev.0` mesmo desmarcada.
- **Confirmações do backend voltaram a aparecer**: mensagens como "4 arquivo(s) adicionado(s)", "Lista limpa." e "Pasta de saída definida." eram enviadas e descartadas pela interface (o aviso de tipos diferentes continua tendo prioridade).
- **Separar PDF com vários arquivos**: cada PDF passa a nomear as próprias páginas; antes todos usavam o nome do padrão e a operação parava no erro "Arquivo ja existe".
- **Início da operação com a janela minimizada**: o `requestAnimationFrame` não dispara nesse estado e o botão *Iniciar* ficava preso na tela "Processando"; agora há um limite de tempo.
- **Rodapé não é mais coberto** pelos botões quando o aviso de tipos diferentes aparece.
- **Código sem uso removido**: painel alternativo nunca exibido, `operationConfig`/badge de status oculta, `state.outputFolder`, variável CSS `--danger`, comandos `windowDrag`/`windowToggleMaximize`, `FolderSummary`/`get_folder_summary`/`_detect_input_pattern` (nunca lidos pela interface) e a opção `open_after_complete`.

## Ajustes da V7

- **Arrastar arquivos corrigido na inicialização do pywebview**: os eventos de drag/drop agora são ligados pelo callback do `webview.start`, conforme o fluxo nativo do pywebview para o WebView2 fornecer o caminho completo (`pywebviewFullPath`).
- Adicionado fallback de consumo no documento inteiro para evitar perda do drop por variações do WebView2.
- **Pin reposicionado** para o canto superior direito do cabeçalho `Central de Processamento`, conforme a referência visual.
- **Área inferior excedente removida**: altura inicial ajustada para **536 × 825 px** e o rodapé passa a acompanhar o conteúdo, sem grande vazio inferior.
- Mantidos o campo único de folha (`13-23`), o padrão sem ponto após `FL` (`FL13-23`) e a abertura por `.pyw/pythonw.exe` sem console.

Conversao do DocFlow Manager para Python mantendo a interface, dimensoes e operacoes do programa original.

## Correcao principal da V5

A V5 **nao usa mais `window.pywebview.api` para os botoes da interface**.
A comunicacao interface <-> Python agora e feita por um servidor local exclusivo em `127.0.0.1`, iniciado dentro do proprio programa. Isso elimina a falha em que a janela abria mas aparecia `O backend do programa ainda não está disponível`.

Antes de mostrar a janela, o programa executa um autoteste no mesmo endpoint usado pelos botoes. Se a comunicacao interna nao estiver funcionando, a janela nem e apresentada como se estivesse pronta.

## Funcionalidades

- Renomear PDF/DWG.
- Unir PDF.
- Separar PDF.
- Unir DWG por automacao COM do AutoCAD.
- Selecionar arquivos.
- Arrastar e soltar arquivos, com fallback para o seletor nativo.
- Escolher pasta de saida.
- Abrir pasta de saida.
- Confirmacao de sobrescrita.
- Manter janela na frente.
- Minimizar, maximizar/restaurar e fechar.
- Reconhecimento de codigo, folha e revisao.

## Abertura sem console / sem flash

Abra `DocFlow_Manager.pyw` ou use o atalho criado por `criar_atalho_menu_iniciar.pyw` / `criar_atalho_menu_iniciar.ps1`.
O atalho chama `pythonw.exe` diretamente e passa o `.pyw` como argumento. O programa principal nao depende de `.bat` para abrir.

`instalar_bibliotecas.bat` serve apenas para instalar dependencias.

## Dependencias

Execute uma vez:

`instalar_bibliotecas.bat`

## Observacao sobre DWG

A uniao de DWG precisa do AutoCAD instalado no Windows e do `pywin32`.


## Ajustes da V5
- Padrão de nome sem ponto após `FL`: `IME-MC-1-44345 FL13-23 Rev.2`.
- Campo **Folha** unificado no formato `13-23`.
- Removida a área de arrastar arquivos; a inclusão é feita diretamente por **Selecionar arquivos**.
- **Saída** permanece abaixo de **Arquivos** e as ações **Limpar lista** / **Iniciar** ficam lado a lado no rodapé do painel.
