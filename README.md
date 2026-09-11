# DOCFLOW MANAGER — PYTHON V8

## Ajustes de nomenclatura — 10/09/2026

- **Nome do arquivo** e **Prévia do nome** agora possuem o mesmo menu de opções, com **Incluir revisão** e **Incluir paginação**. As opções ficam sincronizadas entre os dois menus.
- **Incluir paginação** controla a inclusão automática de `FL inicial-final` no nome gerado.
- Em **Unir PDF**, a prévia continua sendo o nome real do arquivo final. Se o nome calculado coincidir com um PDF de origem, o programa acrescenta **Unificado** antes de `.pdf`, evitando substituir a folha original.
- Como proteção adicional, o backend também impede que a união sobrescreva silenciosamente um dos PDFs de entrada.
- Mantido o cálculo automático da **Folha final** conforme a quantidade de arquivos adicionados.

## Ajustes da V8

- **Nenhuma aba com barra de rolagem**: o campo de padrão ganhou o rótulo "Nome do arquivo", deixando *Padrão* e *Parâmetros* com a mesma estrutura de duas linhas (112 px e 113 px) - antes a troca de aba somava 21 px e fazia a barra aparecer. Para compensar, o botão "Selecionar arquivos" saiu: a área de arrastar já abria a janela de seleção no clique e passou a dizer isso ("Arraste os arquivos aqui ou clique para selecionar"). A janela mínima sem rolagem caiu de 1051 px para 1030 px de altura.
- **Aba "Parâmetros" ao lado de "Padrão"**: a área do padrão e da prévia do nome virou um par de abas. *Padrão* mantém o campo de nome, o menu "Incluir revisão" e a prévia; *Parâmetros* usa o mesmo espaço para a disposição da união de DWG (colunas × linhas, espaçamento X e Y e ordem de preenchimento). A aba só aparece na operação *Unir DWG* - nas demais a interface volta sozinha para *Padrão*.
- **Primeiro desenho fora da célula**: a medição (`GetBoundingBox`) do primeiro bloco falhava calada - o AutoCAD costuma recusar a chamada logo depois da inserção -, o desenho entrava na grade como se tivesse tamanho zero e terminava no centro da célula em vez do canto (medido no arquivo unido: `min` em `420,50 / -297,00`, exatamente metade de uma folha A1 de `841 × 594`). A medição passou a usar o mesmo retry das demais chamadas COM e é refeita após um regen; se ainda assim falhar, o desenho é alinhado pelo enquadramento mediano dos outros em vez de virar tamanho zero, e o log avisa. O log também registra o tamanho medido de cada desenho.
- **Unir DWG em grade**: os desenhos deixaram de ser enfileirados em uma faixa horizontal infinita. Sem nada preenchido a grade é automática e o mais próxima possível de um quadrado (8 desenhos → 3 × 3); digitando as colunas, as linhas são calculadas pela quantidade de desenhos (e vice-versa), como já acontece na folha inicial/final. O espaçamento X/Y é dado em unidades do desenho e, em branco, volta ao cálculo automático (2% do desenho, mínimo de 1000). A grade cresce para a direita e para baixo a partir da origem, e desenhos de tamanhos diferentes ficam centralizados na própria célula.
- **Folha dividida em inicial e final**: o campo único `13-23` deu lugar a dois campos (`Folha inicial` e `Folha final`). Ao digitar em um deles, o outro é recalculado **na hora**. Ao adicionar ou remover arquivos, a **Folha final** é atualizada automaticamente pela quantidade de folhas, mantendo a Folha inicial (ex.: inicial `1` + 10 PDFs → final `10`).
- **Aviso de tipos diferentes**: quando a lista mistura extensões (ex.: 10 DWG + 1 PDF em *Renomear*) ou contém arquivos que a operação escolhida ignora (*Unir PDF* com DWG, *Unir DWG* com PDF), o rodapé da lista de arquivos mostra um aviso com ícone laranja ao lado da contagem (“A seleção contém arquivos de tipos distintos: 9 DWG e 1 PDF.”) e uma confirmação aparece antes de iniciar.
- **Renomear usa o formato majoritário**: com a lista misturada, só o formato mais numeroso é renomeado (10 DWG + 1 PDF renomeia os 10 DWG e mantém o PDF como está), porque o arquivo avulso costuma ser engano na seleção. A faixa de folhas e a prévia já consideram apenas esse grupo.
- **Notificações unificadas**: acabaram os diálogos nativos do navegador ("127.0.0.1 diz") e os toasts (em qualquer posição da janela). Toda mensagem usa um único card central no estilo do programa, sem barra vertical: confirmação com *Cancelar* / *Continuar*, sucesso com *OK* / *Abrir pasta* e falha com uma frase curta e *OK*. Avisos de estado ficam no rodapé da lista de arquivos, junto da contagem.
- **Unir DWG no AutoCAD 2027**: a partir dessa versão o AutoCAD recusa pontos 3D enviados como tupla comum (erro `-2147024809` / `E_INVALIDARG`), o que fazia toda união falhar já no primeiro desenho. Os pontos passam a ser enviados como array tipado de doubles (`VT_ARRAY | VT_R8`), compatível também com as versões anteriores.
- **Retry cobre o AutoCAD ocupado**: quando o programa está processando, o pywin32 às vezes levanta `AttributeError` em vez do erro COM de "chamada rejeitada"; agora essa situação também é repetida em vez de derrubar a operação.
- **Mensagens curtas**: todo texto de notificação é uma frase direta, sem explicações. As falhas perdem o horário do log e o erro técnico da biblioteca dá lugar a algo como “Não foi possível ler o arquivo “prancha.pdf”.”
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
