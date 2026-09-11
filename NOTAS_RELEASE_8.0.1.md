### Interface e recuperação da janela

- A janela ganhou um contorno de 1 px do cabeçalho para baixo — sem ele, a
  janela sem moldura se confundia com o que estivesse atrás.
- O campo **Revisão** encolheu e o espaço foi para o **Código do desenho**,
  que era o campo apertado.
- A nota explicativa saiu da guia **Atualização**.
- Ao arrastar arquivos, a área de arquivos passa a mostrar um alvo de soltura
  maior que a faixa de 40 px, que o ícone de arrasto do Windows costumava
  cobrir. Soltar em qualquer ponto da janela continua valendo.
- **Janela em branco corrigida**: quando o programa era finalizado à força, os
  processos do WebView2 podiam sobreviver segurando a pasta de dados, e a
  abertura seguinte mostrava uma janela vazia sem explicar nada. Agora o
  programa encerra essas sobras, avisa o que houve e fecha, em vez de abrir em
  branco.
