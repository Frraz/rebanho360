"""Textos do botão de informação ("i") das telas.

Um tópico explica, em linguagem de quem usa a fazenda: para que serve o
cadastro ou a movimentação, como ele se liga ao resto do sistema e o que
acontece nas situações que geram dúvida. Não é manual de tela (o que cada botão
faz está na própria tela) — é o "porquê" e o "e depois?".

Estrutura de cada tópico:
- `titulo`: aparece no painel.
- `resumo`: parágrafos de "Para que serve".
- `relacoes`: (nome, texto) — com o que o registro conversa.
- `perguntas`: (pergunta, resposta) — dúvidas de quem está começando. A
  resposta é um texto ou uma lista de parágrafos.

Os textos descrevem o que o sistema FAZ hoje. Mudou uma regra em
`docs/regras-negocio/`? Ajuste o tópico junto: ajuda desatualizada é pior que
nenhuma. Texto puro (o template escapa): nada de HTML aqui.
"""

AJUDA: dict[str, dict] = {
    # ------------------------------------------------------------------ Entrada
    "empresa": {
        "titulo": "Empresas",
        "resumo": [
            "A empresa é quem opera as fazendas: o CNPJ (ou o grupo) em nome de quem as safras são abertas e as fazendas são organizadas.",
            "Cadastre os dados formais uma vez (razão social, CNPJ, endereço, telefone). O resto do sistema só aponta para ela, sem copiar esses dados.",
        ],
        "relacoes": [
            (
                "Safras",
                "Toda safra pertence a uma empresa. Duas empresas têm calendários próprios, que nunca se misturam.",
            ),
            (
                "Unidades e fazendas",
                "A empresa agrupa unidades (divisões do negócio) e as unidades agrupam as fazendas.",
            ),
            (
                "Contexto no topo da tela",
                "O seletor Empresa · Safra · Fazenda usa este cadastro. O que você escolhe lá vale para todas as telas.",
            ),
        ],
        "perguntas": [
            (
                "Preciso cadastrar mais de uma empresa?",
                "Só se a operação tiver mais de um CNPJ com safras próprias. Para uma operação só, uma empresa basta.",
            ),
            (
                "Posso excluir uma empresa?",
                "Esta tela não exclui: safras e unidades dependem dela, e o sistema preserva o histórico. Para corrigir um dado, use Editar.",
            ),
            (
                "Se eu mudar o nome, os registros antigos mudam?",
                "As telas passam a mostrar o nome novo, porque os registros apontam para a empresa em vez de copiar o nome. PDFs que já foram gerados continuam como foram emitidos.",
            ),
        ],
    },
    "unidade": {
        "titulo": "Unidades",
        "resumo": [
            "A unidade é uma divisão de negócio dentro da empresa, como uma região ou um tipo de operação (recria, engorda). Serve para agrupar fazendas.",
            "Pode haver uma só. Quem não precisa dividir a operação cria uma unidade única e segue em frente.",
        ],
        "relacoes": [
            ("Empresa", "Cada unidade pertence a uma empresa."),
            (
                "Fazendas",
                "Cada fazenda pode ser ligada a uma unidade. É por ela que as fazendas ficam agrupadas.",
            ),
        ],
        "perguntas": [
            (
                "Para que serve o código?",
                "É um identificador curto da unidade (por exemplo, SUL). Não se repete dentro da mesma empresa.",
            ),
            (
                "Preciso de várias unidades?",
                "Só se você quiser enxergar o negócio por regiões ou operações. Se não, uma é suficiente.",
            ),
        ],
    },
    "safra": {
        "titulo": "Safras",
        "resumo": [
            "Safra é o período de apuração do negócio: o intervalo em que você mede e compara resultados (por exemplo, 2025/2026, de 01/07/2025 a 30/06/2026). Tem data de início, data de fim e pertence a uma empresa.",
            "Toda compra, venda, custo, movimentação de rebanho e título leva uma safra, definida pela data do lançamento. Lançar algo com data dentro do período faz o registro cair naquela safra.",
        ],
        "relacoes": [
            (
                "Lançamentos",
                "Compras, vendas, custos, movimentações e títulos são separados por safra. É isso que permite comparar uma safra com a outra.",
            ),
            (
                "Painel e relatórios",
                "Mostram a safra escolhida no topo da tela. Trocar a safra lá muda os números, não os dados.",
            ),
            (
                "Rebanho e lotes",
                "O saldo do rebanho atravessa todas as safras. O que a safra separa são os lançamentos do período.",
            ),
            (
                "Períodos",
                "As safras de uma mesma empresa não podem se sobrepor: o sistema recusa datas que invadam outra safra.",
            ),
        ],
        "perguntas": [
            (
                'O que significa "Corrente"?',
                [
                    "É a safra que o sistema abre por padrão para quem entra e que serve de referência para o painel. Só uma safra por empresa pode ser a corrente.",
                    "Tornar corrente troca a marca e já coloca a safra escolhida no topo da sua tela. Ser corrente não impede lançar nas outras: cada lançamento vai para a safra da data informada.",
                    "Cada pessoa também pode olhar outra safra pelo seletor do topo sem mudar qual é a corrente.",
                ],
            ),
            (
                "Qual a diferença entre Aberta e Encerrada?",
                [
                    "Aberta: aceita lançamentos normalmente.",
                    "Encerrada: a safra está fechada para alterações. Só o administrador consegue fazer novos lançamentos nela, e corrigir ou excluir o que já existe exige reabrir a safra. Os demais usuários recebem um aviso explicando. Consultar e emitir relatórios continua livre para todos.",
                ],
            ),
            (
                "O que acontece quando a safra acaba? Preciso cadastrar outra?",
                [
                    "A data final passar não encerra nem troca nada sozinha. Mas um lançamento com data depois do fim precisa de uma safra que cubra aquela data, e sem ela o sistema avisa que não há safra cadastrada.",
                    "Por isso, cadastre a próxima safra antes da virada, começando no dia seguinte ao fim da anterior. Depois torne a nova corrente e, quando as contas da anterior estiverem conferidas, encerre a anterior.",
                ],
            ),
            (
                "A nova safra vem zerada ou com o histórico da anterior?",
                [
                    "Depende do que você olha. O rebanho não zera: o saldo é a soma de todas as entradas e saídas desde o início, então animais, lotes e fazendas continuam lá. A nova safra já começa com o que sobrou da anterior, sem precisar lançar saldo inicial.",
                    "Já os números do período (comprado, vendido, custos, títulos, custo por arroba) são calculados por safra: na nova eles começam em zero e vão se formando. A safra anterior permanece inteira, para consultar e comparar.",
                    "Um lote não é cortado ao meio na virada: continua o mesmo, com o mesmo código e o mesmo histórico de custo. As vendas dele entram na safra da data da venda.",
                ],
            ),
            (
                "O que acontece se eu encerrar uma safra?",
                [
                    "Nada é apagado nem movido: só a situação muda para Encerrada. Encerrar também não muda qual é a corrente, então torne a próxima corrente antes.",
                    "A partir daí, só o administrador faz novos lançamentos nela. Corrigir ou excluir compras, vendas e custos da safra, e desfazer uma baixa de pagamento, exige antes reabri-la. Pagamentos ainda podem ser baixados, porque dinheiro que sai ou entra não depende de competência.",
                    "Encerrar é reversível: o administrador pode reabrir, e a reabertura fica na auditoria. O melhor momento é depois de conferir lançamentos, custos e vendas do período.",
                ],
            ),
            (
                "Esqueci um lançamento da safra passada. E agora?",
                "Peça ao administrador. Ele pode fazer o lançamento direto na safra encerrada ou reabri-la, lançar e encerrar de novo. Para corrigir algo que já existia, a safra precisa ser reaberta. Tudo fica registrado na auditoria.",
            ),
        ],
    },
    "fazenda": {
        "titulo": "Fazendas",
        "resumo": [
            "A fazenda é o lugar onde o rebanho fica. Quase tudo no sistema acontece em uma fazenda: o saldo de animais, os lotes, os custos e as vendas.",
            "Código, localização e áreas (total e de pastagem) identificam a propriedade. As áreas são informativas.",
        ],
        "relacoes": [
            ("Unidade", "A fazenda pode pertencer a uma unidade da empresa."),
            (
                "Áreas / Pastos",
                "As subdivisões da fazenda são cadastradas em Áreas / Pastos.",
            ),
            (
                "Lotes e rebanho",
                "Cada lote fica em uma fazenda. O saldo de animais é calculado por fazenda, lote e categoria. Uma transferência tira animais de uma fazenda e põe em outra, na mesma operação.",
            ),
            (
                "Custos e financeiro",
                "Todo custo é apropriado a uma fazenda, e os títulos também. É assim que se vê quanto cada propriedade consome.",
            ),
            (
                "Usuários",
                "Cada pessoa enxerga apenas as fazendas liberadas para ela. Administrador e gestor veem todas.",
            ),
        ],
        "perguntas": [
            (
                "Como libero uma fazenda para alguém?",
                "Em Usuários e acessos: ao criar ou editar o usuário, escolha as fazendas e se a pessoa só consulta ou também lança.",
            ),
            (
                "Por que uma fazenda não aparece para mim?",
                "Porque ela não está liberada para o seu usuário. O sistema responde como se ela não existisse, de propósito: não confirma nem a existência de registros fora do seu acesso.",
            ),
            (
                "O seletor Fazenda no topo muda o quê?",
                "Filtra telas, painel e relatórios para aquela fazenda. Escolhendo Todas, você vê o consolidado das fazendas a que tem acesso.",
            ),
        ],
    },
    "pasto": {
        "titulo": "Áreas / Pastos",
        "resumo": [
            "São as subdivisões de cada fazenda (também conhecidas como retiros): pastagem, silagem, benfeitoria, reserva/APP e arrendamento. Cada uma pode ter área em hectares e capacidade em UA.",
            "Hoje é um cadastro de referência para o manejo. O saldo do rebanho é por fazenda, lote e categoria, e não por pasto: nenhum cálculo usa estes dados ainda.",
        ],
        "relacoes": [
            ("Fazenda", "Toda área pertence a uma fazenda."),
            (
                "Rebanho",
                "Os animais não são lançados por pasto. Eles ficam no lote, e o lote na fazenda.",
            ),
        ],
        "perguntas": [
            (
                "Preciso cadastrar pastos para lançar animais?",
                "Não. Compras, movimentações e vendas funcionam sem nenhum pasto cadastrado.",
            ),
            (
                "O que é UA?",
                "Unidade Animal: por convenção, 1 UA equivale a 450 kg de peso vivo. A capacidade em UA diz quantos animais, em peso, a área comporta.",
            ),
        ],
    },
    "parceiro": {
        "titulo": "Parceiros",
        "resumo": [
            "Parceiro é qualquer pessoa ou empresa com quem você negocia: quem vende gado, quem compra, o frigorífico, o transportador, o motorista, o comissionado e o favorecido de um pagamento.",
            "É um cadastro só, e cada parceiro pode ter vários papéis. Quem vende e também compra continua sendo uma pessoa só.",
        ],
        "relacoes": [
            ("Compras", "O vendedor do gado é um parceiro."),
            (
                "Vendas e abates",
                "O comprador ou o frigorífico é um parceiro. A venda gera a conta a receber dele.",
            ),
            (
                "Compromissos e acertos",
                "Produtor, comprador, transportador, motorista e comissionado saem deste cadastro.",
            ),
            (
                "Financeiro",
                "O favorecido de um título a pagar é um parceiro, e o título aponta para a conta bancária dele.",
            ),
            (
                "Regras de comissão",
                "O comissionado de cada regra é um parceiro com o papel correspondente.",
            ),
        ],
        "perguntas": [
            (
                "Como acho só os compradores, ou só os transportadores?",
                "Use o filtro Papel ao lado da busca. Ele combina com o texto digitado: papel Comprador e a cidade Gurupi, por exemplo.",
            ),
            (
                "O mesmo produtor vende e compra. Cadastro duas vezes?",
                "Não. Cadastre uma vez e marque os dois papéis. Duplicar a pessoa quebra o histórico dela.",
            ),
            (
                "E os dados bancários?",
                "Ficam no cadastro do parceiro. O título só aponta para a conta, e ninguém digita número de conta no pagamento. O número completo só aparece para financeiro, gestor e administrador, e cada consulta fica registrada na auditoria.",
            ),
        ],
    },
    "categoria": {
        "titulo": "Categorias",
        "resumo": [
            "Categoria é a classificação do animal por sexo e idade, como Machos 13 a 24 meses ou Bezerras mamando. É por categoria que o sistema conta o rebanho, que a compra e a venda são lançadas e que o animal evolui de uma fase para a outra.",
            "A ordem etária define a sequência dentro do mesmo sexo: é com ela que o sistema sugere a próxima categoria.",
        ],
        "relacoes": [
            (
                "Rebanho",
                "O saldo é calculado por categoria dentro de cada fazenda e lote.",
            ),
            (
                "Compras e vendas",
                "Cada compra e cada venda informa a categoria dos animais.",
            ),
            (
                "Evolução e reclassificação",
                "As duas movimentações trocam a categoria: saem da antiga e entram na nova.",
            ),
            (
                "Regras de comissão",
                "Uma regra pode valer só para uma categoria.",
            ),
        ],
        "perguntas": [
            (
                "O animal muda de categoria sozinho quando completa a idade?",
                "Não. O sistema só sugere a categoria seguinte. Mudar é um lançamento seu, do tipo Evolução, com a data que você escolher. Quem conhece o rebanho decide quando.",
            ),
            (
                "Qual a diferença entre evolução e reclassificação?",
                "Evolução é o animal que mudou de fase por idade. Reclassificação é a correção de uma categoria lançada errada. Nas duas, o saldo sai de uma categoria e entra na outra, na mesma operação.",
            ),
            (
                "Posso criar uma categoria nova?",
                "Pode. O cadastro é parametrizável. Cuide da ordem etária para a sugestão de evolução continuar certa.",
            ),
        ],
    },
    "raca": {
        "titulo": "Raças",
        "resumo": [
            "A raça descreve o lote (por exemplo, Nelore). Serve para agrupar e comparar o desempenho entre lotes.",
        ],
        "relacoes": [
            ("Lotes", "Cada lote pode ter uma raça. É o único lugar onde ela aparece."),
        ],
        "perguntas": [
            (
                "Preciso informar a raça?",
                'Não. É opcional no lote. Sem raça, o lote funciona normalmente e aparece com "—".',
            ),
        ],
    },
    "lote": {
        "titulo": "Lotes",
        "resumo": [
            "Lote é um grupo de animais acompanhado do ingresso até a venda. É a unidade em que o sistema mede custo e desempenho: quanto custou, quanto ganhou de peso e quanto rendeu na venda.",
            "O lote não guarda número de cabeças nem peso. Esses números saem das movimentações, sempre calculados na hora, e por isso nunca ficam desencontrados.",
        ],
        "relacoes": [
            (
                "Compras",
                "Confirmar uma compra cria o lote (ou usa um existente) e dá a entrada dos animais nele.",
            ),
            (
                "Movimentações",
                "O saldo do lote é a soma das entradas e saídas dele. Transferir ou mudar de categoria move animais entre posições.",
            ),
            (
                "Pesagens",
                "Duas pesagens do mesmo lote em datas diferentes dão o ganho médio diário (GMD).",
            ),
            (
                "Custos",
                "Custo lançado com o lote é direto e vai inteiro para ele. Custo da fazenda sem lote é rateado entre os lotes.",
            ),
            (
                "Vendas",
                "A venda tira animais do lote e mostra o resultado: receita menos custos.",
            ),
            (
                "Fazenda e safra",
                "O lote fica em uma fazenda e guarda a safra em que entrou.",
            ),
        ],
        "perguntas": [
            (
                "Quando um lote é encerrado?",
                "Sozinho, quando uma venda leva o saldo dele a zero. A data da venda vira a data de saída. Se essa venda for desfeita e o lote voltar a ter animais, ele é reaberto.",
            ),
            (
                "Por que não posso digitar a quantidade de animais do lote?",
                "Porque a quantidade é consequência das movimentações. Se fosse um campo, poderia divergir do que realmente entrou e saiu. Para mudar o número, lance a movimentação certa.",
            ),
            (
                "O lote atravessa a virada de safra?",
                "Sim. Ele continua o mesmo, com o mesmo código e histórico. Cada compra, venda e custo dele entra na safra da própria data.",
            ),
        ],
    },
    "classe_carcaca": {
        "titulo": "Classes de carcaça",
        "resumo": [
            "São as classificações que o frigorífico dá à carcaça (magro, gordura escassa, mediana e assim por diante), usadas para pagar o animal. O cadastro é parametrizável, porque cada frigorífico classifica de um jeito.",
        ],
        "relacoes": [
            (
                "Romaneio do acerto",
                "Cada linha do romaneio combina classificação, faixa, cabeças e peso de carcaça. O valor do animal sai dessas linhas.",
            ),
            (
                "Compromisso",
                "O preço da arroba, por faixa de 1 a 5, vem do contrato. A classe só ajuda a escolher a faixa.",
            ),
        ],
        "perguntas": [
            (
                "Para que serve a faixa sugerida?",
                "Só preenche a faixa no romaneio como sugestão. Quem escolhe a faixa de cada linha é você, e o preço continua editável.",
            ),
            (
                "O preço fica aqui?",
                "Não. O preço é negociado no compromisso. Aqui está só a lista de classificações.",
            ),
        ],
    },
    "tributo": {
        "titulo": "Tributos e taxas",
        "resumo": [
            "São os tipos de tributo, taxa, desconto, adiantamento e crédito que podem aparecer no acerto de uma compra. Aqui se cadastra só o nome e a natureza.",
            "Não há alíquota nem fórmula: o valor é digitado a cada acerto. A regra tributária não foi confirmada com o contador, e calcular por dedução poderia gerar passivo.",
        ],
        "relacoes": [
            (
                "Tributo e taxa",
                "Somam ao custo de aquisição do gado e viram um título de impostos.",
            ),
            (
                "Desconto",
                "Reduz o valor dos animais, tanto no custo quanto no que se paga ao vendedor.",
            ),
            (
                "Adiantamento e crédito",
                "Reduzem só o líquido a pagar ao vendedor. O custo do gado não muda.",
            ),
        ],
        "perguntas": [
            (
                "Por que o sistema não calcula o imposto sozinho?",
                "Porque a regra ainda não foi validada com o contador. Digitar o valor evita um cálculo errado que ninguém notaria.",
            ),
            (
                "A natureza muda alguma coisa?",
                "Sim: é ela que decide o efeito do valor no acerto (some ao custo, reduz o valor dos animais ou reduz só o líquido a pagar).",
            ),
        ],
    },
    "comissao": {
        "titulo": "Regras de comissão",
        "resumo": [
            "Definem quanto se paga de comissão ao comissionado (o corretor, por exemplo): por comprador e por categoria, com período de vigência. A comissão pode ser um percentual ou um valor por cabeça.",
            "O percentual pode incidir sobre o valor bruto (os animais) ou sobre o líquido (bruto menos frete e tributos). Cada regra escolhe a sua base.",
        ],
        "relacoes": [
            (
                "Compromisso",
                "Ao aprovar o compromisso, a regra aplicada é copiada para ele. A partir daí, o compromisso tem a própria comissão.",
            ),
            (
                "Acerto",
                "A comissão entra no custo de aquisição do gado e vira um título a pagar ao comissionado.",
            ),
            (
                "Parceiros",
                "O comissionado é um parceiro cadastrado. Sem comissionado na regra, ela vale para qualquer um.",
            ),
        ],
        "perguntas": [
            (
                "Se eu mudar uma regra, os compromissos antigos mudam?",
                "Não. A regra é copiada no momento da aprovação. Mudar o cadastro em março não altera uma operação aprovada em janeiro.",
            ),
            (
                "Qual a diferença entre base bruta e líquida?",
                "Bruta é o valor dos animais. Líquida é esse valor menos frete e tributos. O mesmo percentual dá comissões diferentes em cada base.",
            ),
        ],
    },
    "centro_custo": {
        "titulo": "Centros de custo",
        "resumo": [
            "Centro de custo é a gaveta em que cada despesa é classificada (funcionários, nutrição, pastagem, sanidade e assim por diante). Responde à pergunta: onde o dinheiro foi?",
            "Pode haver subcentros. O critério de rateio define como o custo que não é de um lote específico é dividido entre os lotes da fazenda.",
        ],
        "relacoes": [
            (
                "Custos",
                "Todo lançamento de custo exige um centro. Sem isso a despesa não pode ser analisada.",
            ),
            (
                "Compras",
                "Ao confirmar uma compra, o sistema lança sozinho os custos de animais, frete, comissão e impostos nos centros correspondentes.",
            ),
            (
                "Lotes e resultado",
                "O custo direto e a parte rateada de cada centro compõem o custo do lote.",
            ),
        ],
        "perguntas": [
            (
                "Qual a diferença entre custo direto e indireto?",
                "Direto tem lote preenchido (compra dos animais, vacina de um lote): vai inteiro para ele. Indireto não tem lote (salário, combustível, herbicida): é da fazenda e é rateado entre os lotes.",
            ),
            (
                "O que é cabeça-dia?",
                "É o critério padrão de rateio: cabeças multiplicadas pelos dias em que ficaram. Um lote que passou o mês todo com 100 cabeças recebe o dobro de custo de outro que ficou meio mês com as mesmas 100.",
            ),
            (
                "Os outros critérios?",
                "Cabeças no fim do período, arroba produzida e manual. O critério usado fica gravado junto do resultado, para o número ser explicável depois.",
            ),
        ],
    },
    # ------------------------------------------------------------ Movimentações
    "compra": {
        "titulo": "Compras",
        "resumo": [
            "Registra o gado comprado: de quem, para qual fazenda, quantas cabeças, peso e valores (animais, frete, comissão, impostos).",
            "Confirmar a compra faz tudo de uma vez: dá entrada no rebanho (criando o lote ou usando um existente), lança os custos e gera os títulos a pagar. Se qualquer parte falhar, nada é gravado.",
        ],
        "relacoes": [
            (
                "Rebanho e lote",
                "A entrada dos animais no lote, na fazenda de destino e na categoria informada, sem digitar de novo em Movimentações.",
            ),
            (
                "Custos",
                "Um lançamento para cada valor preenchido. Animais, frete, comissão e impostos viram custo direto do lote.",
            ),
            (
                "Financeiro",
                "Um título a pagar por componente. O dos animais já tem o vendedor como favorecido. Os outros ficam a definir.",
            ),
            (
                "Safra",
                "Definida pela data da compra.",
            ),
            (
                "Ciclo de compra",
                "Compras que nasceram de um acerto aprovado aparecem aqui, mas só se corrigem reabrindo o acerto.",
            ),
        ],
        "perguntas": [
            (
                "Qual a diferença entre rascunho e confirmada?",
                "Rascunho ainda não afeta nada. Confirmada já deu entrada no rebanho, lançou custos e gerou títulos.",
            ),
            (
                "Errei um dado depois de confirmar. E agora?",
                "Dá para editar, informando o motivo: o sistema desfaz os efeitos da versão antiga e aplica os da nova, na mesma operação. Excluir mostra antes o que será desfeito. Pagamento já baixado bloqueia a correção, e a mensagem diz o caminho.",
            ),
            (
                "Se eu clicar duas vezes em confirmar, a compra duplica?",
                "Não. A confirmação é protegida: uma compra gera uma entrada, um custo e um título por componente, não importa quantas vezes seja pedida.",
            ),
            (
                "Como o custo por arroba é calculado?",
                'Custo de aquisição dividido pelas arrobas do peso total (peso dividido por 15). Sem peso informado, aparece "—".',
            ),
        ],
    },
    "compromisso": {
        "titulo": "Compromissos",
        "resumo": [
            "O compromisso é o contrato de compra feito com o produtor antes de o gado chegar: quem vende, para qual fazenda, o comprador (se houver), a programação (retirada, abate, caminhões) e os itens com o preço por faixa de arroba ou por cabeça.",
            "O ciclo segue esta ordem: compromisso, aprovação, viagem, recebimento, romaneio e acerto. Só o acerto aprovado vira compra.",
        ],
        "relacoes": [
            ("Parceiros", "Produtor, comprador, transportador e comissionado."),
            (
                "Regras de comissão",
                "Ao aprovar o compromisso, a regra aplicada é gravada nele.",
            ),
            (
                "Viagem e recebimento",
                "Cada caminhão é uma viagem. O que chegou é registrado no recebimento, e a quebra de viagem é a que você digita.",
            ),
            (
                "Acerto",
                "Fecha as contas e gera as compras, o rebanho, os custos e os títulos.",
            ),
        ],
        "perguntas": [
            (
                "Aprovar o compromisso mexe no rebanho?",
                "Não. Aprovar libera viagem, recebimento e acerto. Nada vira compra, custo ou título até o acerto ser aprovado.",
            ),
            (
                "O gado que chegou já está no saldo?",
                "Ainda não. Entre o recebimento e a aprovação do acerto o gado não está no saldo, e o painel avisa.",
            ),
            (
                "Em que etapa o compromisso está?",
                "A etapa é calculada do que existe (viagem, recebimento, acerto). Se você excluir um recebimento, ela volta sozinha.",
            ),
            (
                "Quem enxerga o ciclo de compra?",
                "Todos, menos o perfil Campo: preço, comissão e frete são dados comerciais.",
            ),
        ],
    },
    "acerto": {
        "titulo": "Acertos",
        "resumo": [
            "O acerto é o fechamento do compromisso: compara o previsto com o realizado (cabeças, peso, valor, frete) e chega ao custo de aquisição e ao valor líquido a pagar ao vendedor.",
            "Aprovar o acerto gera, para cada item recebido, uma compra confirmada, com entrada no rebanho, custos e títulos. Reabrir desfaz tudo, com motivo.",
        ],
        "relacoes": [
            (
                "Valores",
                "Valor dos animais é a soma dos itens menos descontos. Custo de aquisição é animais + frete + tributos e taxas + comissão. Líquido ao vendedor é animais menos adiantamentos e créditos.",
            ),
            (
                "Distribuição entre os itens",
                "Com mais de um item recebido, você informa quanto de frete, comissão, tributos e descontos é de cada item. O sistema não rateia sozinho: a tela traz uma sugestão (por cabeça recebida, ou pelo valor nos descontos), que só vale depois de salva, e a soma tem de fechar com o total.",
            ),
            (
                "Financeiro",
                "Os títulos nascem com favorecido: frete ao transportador, comissão ao comissionado e os animais ao vendedor, pelo líquido.",
            ),
        ],
        "perguntas": [
            (
                "O que impede de aprovar?",
                "Pendências, e o sistema diz qual: um item por arroba sem romaneio, nenhum animal recebido, uma distribuição entre itens que não fecha com o total e assim por diante. Avisos (como chegar mais cabeças que o compromisso, ou categoria diferente da prevista) alertam, mas não bloqueiam.",
            ),
            (
                "Quem aprova?",
                "Administrador e gestor.",
            ),
            (
                "Depois de aprovado, posso corrigir?",
                "Itens, viagens, recebimentos e romaneio ficam travados. O caminho é reabrir o acerto, com motivo. A reabertura é bloqueada por baixa de título, nota fiscal registrada ou safra encerrada, e a mensagem mostra o caminho.",
            ),
            (
                "Aprovar duas vezes cria compras duplicadas?",
                "Não. Há uma compra por item e um título por componente, mesmo que duas pessoas aprovem ao mesmo tempo.",
            ),
        ],
    },
    "posicao": {
        "titulo": "Posição do rebanho",
        "resumo": [
            "É a fotografia do rebanho em uma data: quantas cabeças há, por categoria, fazenda e lote. Não é um cadastro: é a soma de todas as entradas menos as saídas até a data escolhida.",
        ],
        "relacoes": [
            (
                "Movimentações",
                "Cada animal contado aqui veio de uma movimentação. A lista de Movimentações mostra a origem de cada número.",
            ),
            (
                "Compras e vendas",
                "Geram sozinhas as entradas e saídas que alimentam a posição.",
            ),
            (
                "Filtros do topo",
                "A fazenda escolhida limita a posição. Em Todas, aparece o consolidado do seu acesso.",
            ),
        ],
        "perguntas": [
            (
                "Posso corrigir o saldo direto aqui?",
                "Não, e é de propósito. Para mudar o saldo, lance a movimentação que faltou ou corrija a errada. Assim sempre dá para explicar de onde cada número veio.",
            ),
            (
                "A posição zera na virada de safra?",
                "Não. O rebanho atravessa as safras: a posição é a soma desde o início, até a data escolhida.",
            ),
            (
                "Por que uma data passada mudou depois de uma correção?",
                "Porque a correção vale para trás: ela é registrada com a data do fato original. Se a contagem errada era de setembro, o saldo de setembro passa a estar certo.",
            ),
            (
                "O saldo pode ficar negativo?",
                "Não. Uma saída maior que o saldo é recusada, com a mensagem dizendo quantas cabeças há.",
            ),
        ],
    },
    "movimento": {
        "titulo": "Movimentações",
        "resumo": [
            "Cada entrada, saída ou transferência de animais é uma movimentação. O saldo do rebanho é a soma delas: ninguém digita o saldo.",
            'Transferência, evolução e reclassificação geram duas linhas na mesma operação: sai de um lugar e entra no outro. Por isso animal nenhum "some" no meio do caminho.',
        ],
        "relacoes": [
            (
                "Entradas",
                "Saldo inicial, compra e nascimento. A compra gera a entrada sozinha.",
            ),
            (
                "Saídas",
                "Venda, abate, morte e consumo ou doação. Venda e abate são gerados pela venda; a morte exige motivo.",
            ),
            (
                "Deslocamentos",
                "Transferência (entre fazendas ou lotes), evolução (mudança de categoria por idade) e reclassificação (correção de categoria).",
            ),
            (
                "Ajuste de inventário",
                "Corrige o saldo depois de uma contagem. É restrito a administrador e gestor e exige motivo.",
            ),
            (
                "Safra e lote",
                "A safra vem da data. O lote carrega o histórico do animal.",
            ),
        ],
        "perguntas": [
            (
                "Posso editar ou excluir uma movimentação?",
                "Sim, informando o motivo. Nada é apagado: o sistema registra uma linha de compensação com a data do fato original, e o saldo passa a estar certo desde aquela data.",
            ),
            (
                'O que significa "Saldo insuficiente"?',
                "Que a saída pedida é maior do que há na posição escolhida (fazenda, lote e categoria). O saldo é conferido no momento de gravar, então dois lançamentos simultâneos não conseguem deixá-lo negativo.",
            ),
            (
                "Por que a data importa tanto?",
                "O saldo é calculado até uma data. Informe a data em que o fato aconteceu, não a de hoje, para a posição histórica ficar correta.",
            ),
        ],
    },
    "pesagem": {
        "titulo": "Pesagens",
        "resumo": [
            "Registra o peso de um lote em uma data. O peso médio é o peso total dividido pelas cabeças pesadas.",
            "Com duas pesagens do mesmo lote em datas diferentes, o sistema calcula o ganho médio diário (GMD).",
        ],
        "relacoes": [
            (
                "Lote",
                "Toda pesagem pertence a um lote. O GMD e o desempenho dele saem dela.",
            ),
            (
                "Compra e venda",
                "A pesagem de entrada e a de saída fecham o cálculo de ganho do lote.",
            ),
            (
                "Rebanho",
                "Pesagem não muda o número de cabeças. Ela mede peso; quem conta cabeça é a movimentação.",
            ),
        ],
        "perguntas": [
            (
                "Lancei a pesagem no dia errado. Como corrijo?",
                "Abra a pesagem na lista e use Editar: dá para mudar a data, o motivo, as cabeças e o peso, com o motivo da correção, que fica na auditoria. O GMD do lote se recalcula. Para tirar a pesagem do cálculo, use Excluir; dá para restaurar depois.",
            ),
            (
                "E se o lote não tiver pesagem de entrada?",
                "O GMD continua existindo, mas cobre só o período pesado, e a tela avisa. O sistema nunca estima o peso de entrada. Se a compra do lote informou o peso, ele serve de peso de entrada.",
            ),
            (
                'Por que o GMD aparece como "—"?',
                'Porque faltam duas pesagens em datas diferentes. Falta de dado aparece como "—", nunca como zero.',
            ),
        ],
    },
    "venda": {
        "titulo": "Vendas e abates",
        "resumo": [
            "Registra a saída de animais de um lote para um comprador ou frigorífico. No abate, entra também o peso de carcaça, e o sistema calcula rendimento e valor por arroba.",
            "Confirmar a venda dá saída no rebanho (conferindo o saldo na hora), gera a conta a receber e, se o lote ficar sem animais, encerra o lote.",
        ],
        "relacoes": [
            (
                "Lote e rebanho",
                "A saída vem do lote, da fazenda e da categoria informados.",
            ),
            (
                "Financeiro",
                "Gera uma conta a receber do comprador, com vencimento pela data mais o prazo.",
            ),
            (
                "Resultado do lote",
                "A receita da venda menos os custos do lote forma o resultado e a margem por arroba.",
            ),
            ("Safra", "Definida pela data da venda."),
        ],
        "perguntas": [
            (
                "O que são rendimento e valor por arroba?",
                "Rendimento é o peso de carcaça dividido pelo peso vivo (em %). A arroba de carcaça equivale a 15 kg, e o valor por arroba é o valor total dividido pelas arrobas de carcaça.",
            ),
            (
                "E se for venda de animal vivo?",
                'Não há carcaça, então os indicadores de carcaça aparecem como "—". A venda funciona do mesmo jeito.',
            ),
            (
                "Posso corrigir ou excluir uma venda?",
                "Sim, com motivo. As cabeças voltam ao lote na data original. Se o recebimento já foi baixado, o sistema bloqueia e mostra o caminho: desfazer a baixa antes.",
            ),
        ],
    },
    "conciliacao": {
        "titulo": "Conciliação de transferências",
        "resumo": [
            "Lista toda saída de deslocamento (transferência, evolução, reclassificação) que não tem a entrada correspondente.",
            "No sistema ela deve estar sempre vazia: cada deslocamento nasce com as duas pontas, na mesma operação. A tela existe para provar isso e mostrar qualquer exceção, como os menos 140 cabeças que a planilha antiga acumulava.",
        ],
        "relacoes": [
            (
                "Movimentações",
                "Cada linha listada aqui é um movimento cuja soma não fecha em zero. Abrir o registro leva ao movimento para investigar.",
            ),
        ],
        "perguntas": [
            (
                "A lista está vazia. Está certo?",
                "Está. Significa que todas as transferências saíram de um lugar e entraram em outro.",
            ),
        ],
    },
    "custo": {
        "titulo": "Custos",
        "resumo": [
            "Cada despesa da operação é um lançamento: data, valor, fazenda, centro de custo e classe (custeio ou investimento).",
            "Com lote preenchido, o custo é direto e vai inteiro para o lote. Sem lote, é da fazenda e é rateado entre os lotes pelo critério do centro de custo.",
        ],
        "relacoes": [
            (
                "Centros de custo",
                "Todo lançamento tem um. É o que permite saber onde o dinheiro foi.",
            ),
            (
                "Compras",
                "Confirmar uma compra gera os custos dela sozinho. Esses lançamentos não se editam aqui: o caminho é corrigir a compra.",
            ),
            (
                "Lotes e resultado",
                "O custo do lote (direto mais rateado) é descontado da receita para formar o resultado.",
            ),
            ("Safra", "Definida pela data do custo."),
        ],
        "perguntas": [
            (
                "Qual a diferença entre custeio e investimento?",
                "Custeio é o gasto da safra (ração, salário, combustível). Investimento é o que fica imobilizado (uma câmera de monitoramento, por exemplo).",
            ),
            (
                "Por que fazenda e centro são obrigatórios?",
                "Porque custo sem fazenda e sem centro não dá para analisar. Na planilha antiga, boa parte do custo ficou sem classificação e impediu qualquer conclusão.",
            ),
            (
                "Como corrijo um custo que veio de uma compra?",
                "Custo gerado por compra só se corrige pela própria compra. Os custos acompanham a correção automaticamente.",
            ),
        ],
    },
    "contas_pagar": {
        "titulo": "Contas a pagar",
        "resumo": [
            "Cada título é uma obrigação de pagar: animais, frete, comissão, impostos ou um lançamento avulso, com valor, vencimento e favorecido. Eles nascem sozinhos quando uma compra é confirmada.",
            "O pagamento segue etapas separadas: a pagar, programado, aprovado e, por fim, pago (ou parcial). Quem aprova não é quem paga.",
        ],
        "relacoes": [
            (
                "Compras",
                "Uma compra gera um título por componente preenchido. Corrigir a compra atualiza os títulos, e excluí-la cancela os que ainda não foram pagos.",
            ),
            (
                "Parceiros",
                "O favorecido e a conta bancária vêm do cadastro do parceiro.",
            ),
            (
                "Pagamentos",
                "Cada baixa registra o dinheiro que saiu, no todo ou em parte.",
            ),
        ],
        "perguntas": [
            (
                'Por que o favorecido aparece como "a definir"?',
                "Frete, comissão e impostos de uma compra direta nascem sem favorecido. Defina-o antes de programar o pagamento: título sem favorecido não se programa.",
            ),
            (
                "Qual a diferença entre programar, aprovar e baixar?",
                "Programar diz quando se pretende pagar. Aprovar autoriza. Baixar registra que o dinheiro saiu. São três passos, feitos por pessoas com permissões diferentes.",
            ),
            (
                "Posso pagar só uma parte?",
                "Pode. A soma das baixas nunca passa do valor do título, e clicar duas vezes não paga duas vezes.",
            ),
            (
                "E se eu der a baixa errada?",
                "O financeiro ou o administrador podem desfazê-la, com motivo. Atenção: isso corrige o sistema, não a transferência feita no banco. Confira o extrato.",
            ),
        ],
    },
    "contas_receber": {
        "titulo": "Contas a receber",
        "resumo": [
            "Cada título é um valor que um comprador ainda deve. Nasce sozinho quando uma venda é confirmada, com vencimento pela data da venda mais o prazo informado.",
            "Diferente do pagar, o recebimento não passa por programação nem aprovação: é baixado direto, no todo ou em parte.",
        ],
        "relacoes": [
            ("Vendas", "Cada venda confirmada gera o título do comprador."),
            (
                "Pagamentos",
                "Cada recebimento registrado é uma baixa, com documento obrigatório (Pix, TED, cheque).",
            ),
        ],
        "perguntas": [
            (
                "O valor total do que ainda vou receber aparece onde?",
                "No resumo do topo: vencidos, vencem hoje, próximos dias, depois e total em aberto. O resumo mostra o que falta e não obedece aos filtros.",
            ),
        ],
    },
    "pagamento": {
        "titulo": "Pagamentos e recebimentos",
        "resumo": [
            "Lista as baixas: cada vez que um título foi pago ou recebido, no todo ou em parte. É o dinheiro que saiu e o que entrou de verdade.",
            "Toda baixa exige um documento (número da TED, ID do Pix, número do cheque), que não se repete no mesmo título.",
        ],
        "relacoes": [
            (
                "Títulos",
                "Cada baixa pertence a um título. A soma delas nunca ultrapassa o valor dele.",
            ),
            (
                "Compras e vendas",
                "Enquanto houver baixa, a compra, a venda e o título ficam bloqueados para correção. O caminho é desfazer a baixa antes.",
            ),
            (
                "Fluxo de caixa",
                "Os relatórios financeiros usam a data da baixa para mostrar o que foi realizado.",
            ),
        ],
        "perguntas": [
            (
                "Posso desfazer uma baixa?",
                "Pode, o financeiro ou o administrador, com motivo. Desfazer no sistema não desfaz a transferência no banco: confira o extrato.",
            ),
            (
                "Posso baixar em safra encerrada?",
                "Pode. Caixa não depende de competência. Já desfazer a baixa nessa situação exige reabrir a safra.",
            ),
        ],
    },
    # --------------------------------------------------- Relatórios e sistema
    "dashboard": {
        "titulo": "Dashboard",
        "resumo": [
            "É a análise da safra: indicadores com comparação, gráficos e tabelas que respondem às perguntas de gestão — quanto o rebanho cresceu, quanto custou, a que preço se comprou e se vendeu, quem está atrasado e quais lotes estão rendendo.",
            "Cada aba cuida de um assunto e carrega só quando você abre. Tudo respeita a safra e a fazenda escolhidas no topo da tela, e os dados são os do próprio sistema, calculados na hora.",
        ],
        "relacoes": [
            (
                "Mesmo número em qualquer lugar",
                "Custo por @, GMD, resultado do lote, mortalidade e rendimento vêm dos mesmos cálculos das telas de lote, venda e movimentação. Se um número aqui for diferente do da tela do registro, é defeito: avise.",
            ),
            (
                "Comparação com a safra anterior",
                "As setas dos indicadores comparam com a safra anterior no mesmo ponto: se a atual está no dia 90, a anterior também vai até o dia 90. Seta e cor trazem sempre o texto da variação e se ela é favorável ou não.",
            ),
            (
                "Quem vê o quê",
                "Compras, vendas, custos, financeiro e ciclo de compra mostram dinheiro e só aparecem para quem pode vê-lo. O pessoal de campo vê o rebanho e o desempenho dos lotes. Cada pessoa só enxerga as fazendas a que tem acesso.",
            ),
            (
                "Gráfico e tabela",
                "Todo gráfico tem uma tabela com os mesmos dados (botão de tabela no canto do cartão) e pode ser baixado como imagem. O botão Texturas nas cores acrescenta padrões às cores, para quem não distingue bem as cores.",
            ),
        ],
        "perguntas": [
            (
                'Por que um gráfico diz "Sem dados neste recorte"?',
                "Porque não há lançamento confirmado que se encaixe na safra e na fazenda escolhidas. Mude o contexto no topo ou lance o que falta.",
            ),
            (
                "O que é o bloco O que merece atenção?",
                "São leituras automáticas dos próprios números: mortalidade acima do limite, lote no prejuízo, título vencido, concentração de compras em um vendedor, alta de preço. Cada uma diz o valor e leva ao registro para você conferir. Os limites usados são os do sistema e podem ser ajustados.",
            ),
            (
                "Por que alguns indicadores aparecem como traço?",
                "Falta dado para calcular: um lote com uma pesagem só não tem GMD, uma venda sem peso de carcaça não tem valor por @, um lote sem compra registrada não tem resultado. O painel avisa quantos registros ficaram de fora e nunca estima o que não foi informado.",
            ),
            (
                "O que a aba Mortes mostra?",
                "Quantas cabeças morreram por mês (jovens e adultos), por causa, categoria, fazenda e lote, e a mortalidade mês a mês. Morte lançada sem causa aparece como Não informada. O sistema não diz o que é mortalidade alta: ele mostra, e a leitura é sua. Jovem é a categoria até 13 a 24 meses.",
            ),
            (
                "O que são as despesas da aba Financeiro?",
                "São os custos lançados e confirmados da safra, por centro de custo e por mês. A compra de animais fica de fora (ela está na aba Compras), e o total é o mesmo da aba Custos.",
            ),
            (
                "O resultado do lote inclui custos que ainda vão chegar?",
                "Inclui o que está lançado até hoje. Lote que ainda tem animais mostra resultado parcial, com o custo rateado pela fração já vendida; ele fecha quando o saldo zera.",
            ),
        ],
    },
    "inicio": {
        "titulo": "Início",
        "resumo": [
            "O painel responde à pergunta do dia: o que preciso fazer agora? As pendências vêm primeiro, depois o rebanho, os indicadores da safra e os últimos lançamentos.",
            "Segue a safra e a fazenda escolhidas no topo da tela.",
        ],
        "relacoes": [
            (
                "Pendências",
                "Cada uma é um link que leva direto ao que precisa de atenção.",
            ),
            (
                "Rebanho",
                "Mostra o saldo atual. Ele não depende da safra escolhida, porque o rebanho atravessa as safras.",
            ),
            (
                "Indicadores da safra",
                "Mostram só o período da safra escolhida. Em uma safra nova, começam baixos e vão se formando.",
            ),
        ],
        "perguntas": [
            (
                'Por que alguns números mostram "—"?',
                "Porque falta dado para calcular (um peso, uma venda). O sistema nunca mostra zero no lugar, para você não confundir falta de dado com resultado zerado.",
            ),
        ],
    },
    "relatorios": {
        "titulo": "Relatórios",
        "resumo": [
            "Reúne todos os relatórios do sistema: compras, programações, acertos, comissões, financeiro e desempenho dos lotes. Os números respeitam a safra e a fazenda escolhidas no topo.",
            "Cada relatório pode ser visto na tela e baixado em CSV, XLSX ou PDF. Use o campo de busca para achar um relatório pelo nome ou pelo assunto; os filtros de comprador, fazenda, período e situação do lote aparecem nos relatórios que os aceitam e saem impressos em Filtros aplicados.",
        ],
        "relacoes": [
            (
                "Permissões",
                "Você só vê os relatórios do seu perfil: os comerciais não aparecem para o Campo, e os financeiros só para quem enxerga títulos.",
            ),
            (
                "Documentos gerados",
                "Os PDFs ficam guardados, com quem gerou, quando e com quais filtros.",
            ),
        ],
        "perguntas": [
            (
                'Por que aparece "—" em alguma coluna?',
                "Falta de dado, não zero. Em alguns relatórios há uma explicação do motivo.",
            ),
            (
                "Onde está o contrato de compra?",
                "No relatório Contrato de compra: ele lista os compromissos aprovados e gera o PDF de cada um. É o mesmo documento do detalhe do compromisso.",
            ),
            (
                "Para que serve o relatório Movimentação por fazenda?",
                "Mostra, por categoria, o saldo anterior, as entradas, as saídas e a posição final de uma fazenda no período, e a lista de cada movimentação. Sai do razão do rebanho, sem lançamento novo.",
            ),
        ],
    },
    "documentos": {
        "titulo": "Documentos gerados",
        "resumo": [
            "Cada PDF emitido pelo sistema fica guardado aqui, com quem gerou, quando, os filtros usados, a versão do layout e a impressão digital do arquivo (hash).",
            "Isso permite provar depois exatamente o que foi impresso e que o arquivo não foi alterado.",
        ],
        "relacoes": [
            (
                "Relatórios e contratos",
                "Os PDFs de relatórios e de contratos de compromisso são gerados e guardados aqui.",
            ),
            (
                "Segurança",
                "O arquivo só é entregue a quem está logado e tem acesso ao registro.",
            ),
        ],
        "perguntas": [
            (
                'Por que o PDF aparece como "gerando"?',
                "Relatórios maiores são montados em segundo plano. A página atualiza sozinha quando o arquivo fica pronto.",
            ),
        ],
    },
    "importacao": {
        "titulo": "Importações",
        "resumo": [
            "Traz dados de planilhas para o sistema (compras, vendas, movimentações, pesagens e custos). Nada entra de imediato: a planilha é lida, validada linha a linha e mostrada numa prévia. Só entra depois de você confirmar.",
        ],
        "relacoes": [
            (
                "Validação",
                "Linhas com erro ficam de fora e explicam o problema. As válidas podem ser importadas.",
            ),
            (
                "Rebanho e custos",
                "O que é importado passa pelas mesmas regras dos lançamentos manuais, inclusive saldo e safra.",
            ),
            (
                "Financeiro",
                "O histórico importado não gera títulos: considera-se que já foi pago fora do sistema. Quando precisar, gere sob demanda pela tela de operações sem título.",
            ),
        ],
        "perguntas": [
            (
                "E se eu enviar a mesma planilha duas vezes?",
                "O sistema detecta e pede confirmação explícita, para evitar registros duplicados.",
            ),
            (
                "Posso importar para uma safra encerrada?",
                "A importação segue a mesma trava dos lançamentos: safra encerrada só aceita o administrador.",
            ),
        ],
    },
    "exportacao": {
        "titulo": "Exportações",
        "resumo": [
            "Leva os dados do sistema para fora: tudo, ou só o que você escolher, em CSV, Excel, JSON ou PDF. Serve para guardar uma cópia, analisar em outra ferramenta ou, se um dia deixar de usar o sistema, não perder nada.",
            "A exportação roda em segundo plano. Você pode sair da tela e voltar: o andamento aparece aqui, e quando termina é só baixar. Se for mais de um arquivo, vem tudo num ZIP com um LEIA-ME e um manifesto que prova que nada mudou.",
        ],
        "relacoes": [
            (
                "Escopo por fazenda",
                "Sai só o que você já enxerga nas telas. Quem não vê o financeiro, a conta bancária ou a auditoria também não os exporta.",
            ),
            (
                "Dados e relatórios",
                "Os conjuntos de dados são o que está gravado (compras, lotes, razão do rebanho, títulos...). Indicadores como peso médio e custo por arroba não são gravados: estão nos relatórios prontos, com os mesmos números das telas.",
            ),
            (
                "Rebanho",
                "O saldo do rebanho é a soma da quantidade no razão. Exporte o razão para recalcular o saldo fora do sistema.",
            ),
            (
                "Auditoria",
                "Cada pedido e cada download ficam registrados na auditoria: quem exportou o quê e quando. O conteúdo exportado não vai para o registro.",
            ),
        ],
        "perguntas": [
            (
                "Quanto tempo o arquivo fica disponível?",
                "30 dias, a contar de quando a exportação termina. Nesse prazo você pode baixar o arquivo e guardá-lo onde quiser. Depois, ele é apagado do servidor automaticamente e não há como recuperá-lo; o pedido continua na lista e dá para pedir de novo.",
            ),
            (
                "Por que a exportação de tudo demora?",
                "Os conjuntos grandes (razão do rebanho, auditoria) têm muitas linhas, e o PDF é o formato mais lento. Por isso ela roda em segundo plano e mostra o andamento.",
            ),
            (
                "Isto é um backup do sistema?",
                "É uma cópia dos dados em formatos abertos, boa para levar e analisar. Não é uma cópia exata do banco no mesmo instante: os conjuntos são lidos um depois do outro. Para o backup completo do servidor, use o backup do deploy.",
            ),
            (
                "O que fica de fora?",
                "Senhas, segredos do segundo fator e códigos de recuperação nunca saem do sistema. Registros excluídos só entram se você marcar essa opção.",
            ),
            (
                "Posso usar o JSON para importar em outro sistema?",
                "Sim. O JSON traz os valores exatos do banco e descreve as próprias colunas. Cada vínculo é o ID do registro, e todo conjunto traz o seu ID, para religar as tabelas.",
            ),
        ],
    },
    "auditoria": {
        "titulo": "Auditoria",
        "resumo": [
            "O registro de tudo o que foi lançado, corrigido ou desfeito: quem fez, quando, o que mudou (antes e depois) e o motivo informado.",
            "É imutável. Não há tela, função ou comando para alterar ou apagar um evento, nem para o administrador. Ele pode apagar um dado, mas não pode apagar o registro de que apagou.",
        ],
        "relacoes": [
            (
                "Todas as telas",
                "Cada ação importante (criar, editar, excluir, confirmar, aprovar, entrar) gera um evento aqui, na mesma operação.",
            ),
            (
                "Cascatas",
                "Uma exclusão que desfaz vários registros aparece agrupada, como um ato só.",
            ),
            (
                "Linha do tempo",
                "Dentro de cada registro, a linha do tempo mostra só o que aconteceu com ele.",
            ),
        ],
        "perguntas": [
            (
                "Quem vê a auditoria?",
                "O administrador. Pode ser configurado para incluir também o gestor.",
            ),
            (
                "Dados sensíveis aparecem aqui?",
                "Não. Senhas e segredos nunca são gravados. Consultas a dados bancários registram só o fato de a consulta ter ocorrido.",
            ),
        ],
    },
    "usuarios": {
        "titulo": "Usuários e acessos",
        "resumo": [
            "Define quem entra no sistema, com que papel e em quais fazendas. O papel diz o que a pessoa pode fazer. As fazendas liberadas dizem onde.",
        ],
        "relacoes": [
            (
                "Administrador",
                "Faz tudo, inclusive gerenciar usuários, ver a auditoria, reabrir safras e lançar em safra encerrada. Vê todas as fazendas. Precisa de segundo fator para entrar.",
            ),
            (
                "Gestor",
                "Vê todas as fazendas, lança, corrige, exclui e restaura, aprova acertos e pagamentos.",
            ),
            (
                "Escritório",
                "Lança e corrige compras, vendas, custos, ciclo de compra e títulos nas fazendas liberadas.",
            ),
            (
                "Campo",
                "Lança o que acontece no campo (movimentações, pesagens) e não vê dados comerciais como preço, comissão e frete.",
            ),
            (
                "Financeiro",
                "Programa, aprova e dá baixa em pagamentos e vê dados bancários. Precisa de segundo fator.",
            ),
            ("Consulta", "Só enxerga. Não lança nem altera nada."),
        ],
        "perguntas": [
            (
                "Para que servem as fazendas por usuário?",
                "Para limitar o alcance. Alguém do Escritório com acesso a uma fazenda não vê as outras, mesmo tendo o mesmo papel. Para cada fazenda, escolha entre só consulta ou consulta e lançamento.",
            ),
            (
                "Excluir um usuário apaga o histórico dele?",
                "Não. A exclusão é lógica: a conta sai do login e da lista, e tudo o que a pessoa fez continua na auditoria.",
            ),
            (
                "O que o sistema não deixa fazer?",
                "Desativar, excluir ou rebaixar a própria conta, e mexer no último administrador ativo. Toda mudança pede motivo e vai para a auditoria.",
            ),
            (
                "Convite por e-mail ou senha temporária?",
                "No convite, a pessoa define a própria senha por um link. Na senha temporária, você repassa e ela é obrigada a trocar ao entrar. Sem e-mail cadastrado, só a senha temporária.",
            ),
        ],
    },
    "conta": {
        "titulo": "Conta",
        "resumo": [
            "É a sua página pessoal: seus dados, a aparência do sistema, a sua senha e a proteção da sua entrada. O que você muda aqui vale só para você.",
        ],
        "relacoes": [
            (
                "Perfil",
                "Usuário (para entrar), nome, sobrenome, telefone, data de nascimento e CPF. Você entra com o usuário ou com o e-mail. E-mail, papel e fazendas são definidos pelo administrador.",
            ),
            (
                "Aparência",
                "Tema claro ou escuro. Ao escolher, a tela já mostra como fica; ele só fica gravado depois de Salvar aparência. A escolha é da sua conta e vale em qualquer aparelho em que você entrar; não muda nada para os outros usuários.",
            ),
            (
                "Senha",
                "Informe a senha atual e escolha uma nova. As outras sessões abertas em outros aparelhos são encerradas. A troca fica registrada na auditoria, sem a senha.",
            ),
            (
                "Segundo fator",
                "O código do aplicativo autenticador, pedido a cada entrada. É opcional, mas recomendado a todos. Você ativa, gera novos códigos de recuperação, revoga dispositivos confiáveis e, se quiser, desativa por aqui (com a senha e um código).",
            ),
        ],
        "perguntas": [
            (
                "O CPF é obrigatório?",
                "Não. Se informar, o sistema confere os dígitos e não aceita o mesmo CPF em duas contas. Só você o vê por inteiro; na auditoria ele aparece mascarado.",
            ),
            (
                "Como troco o meu e-mail?",
                "Peça ao administrador. O e-mail é por onde a senha é recuperada, então a troca passa por ele.",
            ),
            (
                "Perdi o celular do segundo fator. E agora?",
                "Entre com um código de recuperação, se ainda tiver. Sem eles, peça ao administrador para redefinir o seu segundo fator e configure de novo.",
            ),
            (
                "Por que o tema só aparece aqui, e não no topo da tela?",
                "Porque é uma escolha que você faz uma vez, não uma ação do trabalho do dia. Escolhida, ela acompanha a sua conta: vale no celular, no computador do escritório e em qualquer lugar em que você entrar.",
            ),
            (
                "Posso desativar o segundo fator?",
                "Pode. Em Segundo fator, use Desativar e confirme com a senha e um código do aplicativo (ou de recuperação). O aplicativo e os códigos são apagados, os dispositivos confiáveis são revogados e a ação fica na auditoria. Dá para ativar de novo quando quiser.",
            ),
        ],
    },
    "solicitacoes": {
        "titulo": "Solicitações de acesso",
        "resumo": [
            "São os pedidos feitos por quem ainda não tem conta, pela tela de entrada. A pessoa informa nome, e-mail e por que precisa de acesso. Não escolhe papel, fazenda nem senha.",
        ],
        "relacoes": [
            (
                "Aprovar",
                "Você escolhe usuário, papel e fazendas. A conta é criada sem senha, e a pessoa recebe um e-mail com o link para definir a dela.",
            ),
            (
                "Recusar",
                "Registra o motivo (uso interno) e, se você quiser, avisa a pessoa sem mostrar o motivo.",
            ),
        ],
        "perguntas": [
            (
                "Por que o link vai para o e-mail do pedido?",
                "Porque só o dono do e-mail consegue definir a senha. É assim que o endereço fica confirmado.",
            ),
            (
                "O pedido recusado some?",
                "Não. Nenhum pedido é apagado. Quem foi recusado pode pedir de novo.",
            ),
        ],
    },
    # --------------------------------------------------- Comercial e fazenda
    "condicao_pagamento": {
        "titulo": "Condições de pagamento",
        "resumo": [
            "A condição de pagamento diz em quantos dias, depois da data da operação, o dinheiro sai (compra) ou entra (venda): à vista, prazo único ou parcelado.",
            "Cada empresa cria as suas. O sistema não impõe uma regra única: você cadastra as condições que realmente pratica e escolhe a de cada operação.",
        ],
        "relacoes": [
            (
                "Compras, compromissos e vendas",
                "Cada operação escolhe uma condição. Ela grava o prazo do primeiro vencimento no momento do lançamento.",
            ),
            (
                "Financeiro",
                "O primeiro prazo é o vencimento do primeiro título. Condição parcelada gera mais de um título.",
            ),
            (
                "Quem cadastra",
                "Administrador, gestor, escritório e financeiro, porque quem lança a operação também precisa criar a condição dela.",
            ),
        ],
        "perguntas": [
            (
                "O que escrevo em Dias?",
                "Os dias depois da data da operação. Um número é à vista (0) ou prazo único (30). Vários separados por vírgula são parcelas: 30,60,90 são três parcelas.",
            ),
            (
                "Posso apagar uma condição?",
                "Esta tela não apaga. Para tirar de uso, edite e desmarque Ativa: ela deixa de ser oferecida em operações novas, e as que já a usam continuam com ela.",
            ),
            (
                "Se eu mudar uma condição, os títulos antigos mudam?",
                "Não. O título nasce com os vencimentos da operação no momento em que ela foi confirmada. Para mudar um vencimento, corrija o título ou a operação, com motivo.",
            ),
        ],
    },
    "reproducao": {
        "titulo": "Reprodução",
        "resumo": [
            "Um ciclo por fazenda e por safra de nascimento: quantas fêmeas entraram na estação de monta, quantas ficaram prenhes (por categoria e por método) e quantos bezerros foram desmamados.",
            "Você informa só o que contou. Vazias, fertilidade, porcentagem de inseminadas e desmama são calculadas desses números.",
        ],
        "relacoes": [
            (
                "Rebanho",
                "Os nascimentos não são digitados aqui. Vêm das movimentações do tipo Nascimento, na fazenda e no período da safra do ciclo.",
            ),
            (
                "Safra",
                "Só pode haver um ciclo por fazenda e safra. Um ciclo excluído não conta.",
            ),
            (
                "Saldo, custo e financeiro",
                "O ciclo é um registro de apoio: não mexe no saldo do rebanho, nem em custo ou título.",
            ),
        ],
        "perguntas": [
            (
                "Como os índices são calculados?",
                "Fertilidade é prenhes dividido por fêmeas em monta. Desmama é desmamados dividido por nascidos. A fertilidade da IA usa as inseminadas, e a do touro usa as que não foram inseminadas.",
            ),
            (
                'Por que a desmama aparece como "—"?',
                'Porque não há nascimentos lançados no rebanho para dividir. Falta de dado aparece como "—", nunca como 0%.',
            ),
            (
                "O sistema diz se um índice é bom ou ruim?",
                "Não. Ele mostra o número. A leitura é do produtor e do consultor.",
            ),
            (
                "Posso corrigir ou excluir um ciclo?",
                "Sim, informando o motivo, e a auditoria guarda o que mudou. Como o ciclo não mexe em rebanho, custo ou título, não há nada mais a desfazer.",
            ),
        ],
    },
    "estrutura": {
        "titulo": "Infraestrutura",
        "resumo": [
            "Cadastro das estruturas da fazenda: currais, cochos, bebedouros, cercas e barracões. Registre a área, os metros de cocho, o número de bebedouros e quantos animais a estrutura atende.",
            "Com isso o sistema calcula razões como metros quadrados por animal, centímetros de cocho por cabeça e animais por bebedouro.",
        ],
        "relacoes": [
            (
                "Fazenda",
                "Cada estrutura pertence a uma fazenda e só aparece para quem tem acesso a ela.",
            ),
            (
                "Custos",
                "O cadastro não gera custo. A despesa de manutenção se lança em Custos, como qualquer outra.",
            ),
            (
                "Quem cadastra",
                "Administrador, gestor e escritório. Os demais perfis consultam.",
            ),
        ],
        "perguntas": [
            (
                'Por que uma razão aparece como "—"?',
                'Porque falta a medida ou o número de animais atendidos. Sem animais, o sistema não divide: mostra "—", não zero.',
            ),
            (
                "Posso excluir uma estrutura?",
                "Não. Para tirar de uso, edite e desmarque Ativa. O cadastro fica, e a auditoria guarda quem mudou o quê.",
            ),
        ],
    },
    "maquina": {
        "titulo": "Parque de máquinas",
        "resumo": [
            "Cada máquina da fazenda (trator, implemento, caminhão, utilitário) e o que ela trabalhou. Você lança o uso, com data, horas, combustível (litros e reais) e manutenção.",
            "O sistema calcula o consumo em litros por hora e o custo por hora do que foi lançado.",
        ],
        "relacoes": [
            (
                "Custos",
                "O uso da máquina não gera custo sozinho. O gasto do parque de máquinas continua sendo lançado em Custos. Aqui o uso serve para medir quanto custa a hora.",
            ),
            (
                "Fazenda",
                "Cada máquina pertence a uma fazenda e só aparece para quem tem acesso a ela.",
            ),
            (
                "Quem lança",
                "Administrador, gestor, escritório e campo lançam o uso, que é dado do campo. Cadastrar a máquina é só dos três primeiros.",
            ),
        ],
        "perguntas": [
            (
                "Como o custo por hora é calculado?",
                'Combustível mais manutenção, dividido pelas horas trabalhadas, somando os usos lançados. Sem combustível nem manutenção informados, aparece "—".',
            ),
            (
                "Lancei um uso errado. E agora?",
                "Edite ou exclua o uso informando o motivo. O custo por hora é recalculado, e a auditoria guarda o que mudou.",
            ),
            (
                "Posso lançar uso de máquina inativa?",
                "Não. Reative a máquina antes. Para tirar uma máquina de operação, desmarque Ativa em vez de excluir.",
            ),
        ],
    },
    # ------------------------------------------------------- Ciclo de compra
    "viagem": {
        "titulo": "Viagens",
        "resumo": [
            "Cada caminhão de um compromisso é uma viagem: transportador, motorista, veículo, placa, ADF, data de retirada, as cargas (cabeças programadas e embarcadas de cada item, e o peso de origem) e o frete.",
            "Só se lança viagem em compromisso aprovado.",
        ],
        "relacoes": [
            (
                "Frete",
                "O previsto sai do critério (por cabeça, por km, por kg de origem ou valor fechado) multiplicado pela tarifa. O realizado é o que foi cobrado, digitado por você.",
            ),
            (
                "Recebimento",
                "Quando o caminhão chega, o recebimento é registrado a partir da viagem.",
            ),
            (
                "Acerto e financeiro",
                "O acerto usa o frete realizado e, sem ele, o previsto, avisando qual usou. Ao aprovar o acerto nasce um título de frete por viagem, com o transportador como favorecido e o vencimento informado na viagem.",
            ),
        ],
        "perguntas": [
            (
                'Por que o frete previsto aparece como "—"?',
                'Porque falta o critério, a tarifa ou o dado que o critério pede (km, cabeças ou o peso de origem de todas as cargas). Falta de dado aparece como "—", nunca como zero.',
            ),
            (
                "A viagem mexe no rebanho?",
                "Não. O gado só entra no saldo quando o acerto é aprovado.",
            ),
            (
                "Posso corrigir a viagem depois do acerto aprovado?",
                "Não diretamente: viagens ficam travadas. O caminho é reabrir o acerto, com motivo.",
            ),
        ],
    },
    "recebimento": {
        "titulo": "Recebimentos",
        "resumo": [
            "Registra o que chegou em cada carga da viagem: cabeças, peso, categoria recebida e ocorrências. O peso de origem e o recebido aparecem lado a lado.",
            "A quebra de viagem é a que você digita. O sistema não a calcula, não alerta por percentual e não desconta nada do valor dos animais.",
        ],
        "relacoes": [
            (
                "Viagem",
                "Todo recebimento pertence a uma viagem. A data não pode ser futura nem anterior à retirada.",
            ),
            (
                "Acerto",
                "As cabeças recebidas valem para os itens por cabeça e para as compras geradas na aprovação.",
            ),
            (
                "Rebanho",
                "O gado recebido ainda não está no saldo. Ele entra quando o acerto é aprovado, e o painel avisa enquanto isso.",
            ),
        ],
        "perguntas": [
            (
                "E se chegou uma categoria diferente da prevista?",
                "Informe a categoria recebida. O acerto mostra um aviso, mas não bloqueia.",
            ),
            (
                "Posso corrigir ou excluir um recebimento?",
                "Sim, informando o motivo, enquanto o acerto não estiver aprovado. Se excluir, a etapa do compromisso volta sozinha.",
            ),
            (
                "Chegaram mais cabeças do que o compromisso previa. Isso bloqueia?",
                "Não. O acerto mostra um aviso com os dois números, e a decisão continua sendo sua.",
            ),
        ],
    },
    "romaneio": {
        "titulo": "Romaneio valorizado",
        "resumo": [
            "O romaneio fecha os itens negociados por arroba. Em cada linha você informa a classificação da carcaça, a faixa de preço, as cabeças e o peso de carcaça.",
            "O sistema calcula as arrobas (peso dividido por 15), o valor bruto (arrobas vezes o preço da @), o desconto e o valor líquido.",
        ],
        "relacoes": [
            (
                "Classificações de carcaça",
                "Vêm do cadastro comercial. Uma classificação inativa não entra em linha nova, e ela pode sugerir uma faixa.",
            ),
            (
                "Compromisso",
                "A faixa, de 1 a 5, busca o preço no item do contrato. O preço pode ser ajustado na linha, e a diferença aparece no acerto.",
            ),
            (
                "Acerto",
                "O valor líquido do romaneio é o valor do item no acerto. Item por arroba sem romaneio é pendência e impede a aprovação.",
            ),
        ],
        "perguntas": [
            (
                "Quem escolhe a faixa?",
                "Você, linha a linha. A classificação só sugere, e nenhuma regra decide por você.",
            ),
            (
                "Item por cabeça tem romaneio?",
                "Não. Ele vale as cabeças recebidas vezes o preço por cabeça.",
            ),
            (
                "O romaneio precisa ter as mesmas cabeças do recebimento?",
                "Não bloqueia. Se os números forem diferentes, o acerto mostra um aviso com os dois.",
            ),
        ],
    },
    # ---------------------------------------------------------- Relatório
    "relatorio": {
        "titulo": "Como ler este relatório",
        "resumo": [
            "O relatório mostra os números da safra e da fazenda escolhidas no topo. Os filtros em uso aparecem listados acima da tabela, e alguns relatórios aceitam também período ou outros parâmetros.",
            "Os números vêm dos mesmos cálculos das telas e do painel. Se um indicador aparece em dois lugares, é o mesmo valor.",
        ],
        "relacoes": [
            (
                "CSV e Excel",
                "Baixam na hora, com os filtros que estão na tela. Cada download fica registrado na auditoria.",
            ),
            (
                "PDF",
                "É gerado e guardado em Documentos gerados, com quem pediu, quando e com quais filtros.",
            ),
            (
                "Escopo",
                "Você só vê dados das fazendas a que tem acesso, mesmo escolhendo Todas.",
            ),
        ],
        "perguntas": [
            (
                "O relatório está vazio. Por quê?",
                "Quase sempre porque a safra, a fazenda ou o período do filtro não têm registro. Confira o topo da tela e os filtros.",
            ),
            (
                'Por que aparece "—" em alguma coluna?',
                "Falta de dado, não zero. Quando há uma nota abaixo dos filtros, ela explica o motivo.",
            ),
            (
                "O arquivo baixado é igual ao da tela?",
                "Sim: usa os mesmos filtros no momento do pedido. Mudou o filtro depois? Baixe de novo.",
            ),
        ],
    },
}


def _como_lista(texto) -> list[str]:
    return [texto] if isinstance(texto, str) else list(texto)


def topico_de_ajuda(slug: str) -> dict | None:
    """Tópico pronto para o template (respostas sempre em lista de
    parágrafos), ou `None` se o slug não existe."""
    topico = AJUDA.get(slug)
    if topico is None:
        return None
    return {
        "titulo": topico["titulo"],
        "resumo": _como_lista(topico["resumo"]),
        "relacoes": list(topico.get("relacoes", [])),
        "perguntas": [(p, _como_lista(r)) for p, r in topico.get("perguntas", [])],
    }
