# PRL3060 Kryptex — protótipo experimental 0.1.0

**Este ficheiro ZIP contém código-fonte. Não é um miner compilado, validado ou pronto a instalar no HiveOS.**

A base é o CPPminer de foolzhz (licença MIT), no commit identificado em UPSTREAM.txt. A adaptação acrescenta um perfil CUDA/cuBLAS para Ampere sm_86, transporte Pearl/Kryptex e integração HiveOS. O motor matemático deriva desse projeto; não é um kernel original otimizado de raiz para a RTX 3060 Ti.

## Equipamento de destino

Informação da captura fornecida:

- 4 × NVIDIA RTX 3060 Ti de 8 GB.
- HiveOS 0.6-231@261005; kernel 6.12.0-hiveos #95.
- Driver NVIDIA 580.173.02.
- Diagnóstico confirmado: glibc 2.35; RAM total 7804 MiB, disponível 4896 MiB; sem swap.
- Referência apresentada pelo ForgeMiner 1.8.5: 228,7 TH/s e 525 W no conjunto. É uma leitura do painel, não uma medição de shares aceites ou do consumo na tomada.
- Pool escolhida: Kryptex.

Não alteramos clocks, power limits, ventoinhas, Flight Sheets existentes ou drivers. Os ficheiros entregues não se instalam nem arrancam sozinhos.

## Estado real

Este ZIP continua a conter apenas código-fonte. A compilação CUDA da sessão anterior terminou, mas os seus artefactos não ficaram preservados. Na reconstrução, o acesso a developer.download.nvidia.com foi bloqueado pela política de rede do ambiente. Não existe neste pacote um executável CUDA disponível para instalar.

As correções de código foram recuperadas. Os testes locais C++ e Python foram novamente executados. Os testes Rust e a receita Docker devem correr numa nova compilação; o workflow incluído executa esses testes antes de empacotar. A compilação por GitHub Actions ainda não foi lançada.

Não há GPU NVIDIA neste ambiente. A execução CUDA numa RTX 3060 Ti, o consumo total de RAM/VRAM, a autorização e as shares aceites na Kryptex continuam por validar. Não existe qualquer medição de hashrate deste protótipo.

O perfil usa o caminho de GEMM int8 do cuBLAS e uma etapa separada de verificação do jackpot. Ainda não possui um kernel fundido otimizado para Ampere. Pode ser substancialmente mais lento que o ForgeMiner/PeakMiner; só um ensaio permite avaliar.

## O que foi adaptado

- Removida a rotina de dev fee desta cópia MIT, incluindo o endereço do programador: 0% de dev fee. A comissão da Kryptex mantém-se.
- Pool por defeito: `stratum+tcp://prl.kryptex.network:7048`.
- Login com `wallet`, `worker`, `pass` e `agent`; aceita um endereço PRL ou um ID da conta Kryptex no campo wallet, sem impor o prefixo `prl1`.
- Esta versão usa TCP. SSL/TLS na porta 8048 ainda não está implementado e é recusado na configuração.
- Parser JSON real, enquadramento por linhas, tratamento de mensagens fragmentadas e de trabalhos recebidos antes da confirmação do login.
- Rejeição de trabalhos sem target explícito, incompletos ou com uma versão de certificado desconhecida. Não se assume silenciosamente uma nova versão do algoritmo.
- A chave de um trabalho considera o cabeçalho completo, o target e a versão do certificado. Mudanças dessas informações cancelam trabalho desatualizado.
- Respostas a shares correlacionadas por ID; enviar uma share não conta como aceitação.
- Batch inicial 4 × 32: histórico de resultados de 512 MiB. As matrizes e as bibliotecas consomem memória adicional. Isto não é uma medição do consumo total de VRAM.
- Um processo por GPU, pastas de provas separadas, estatísticas por placa e saída com erro quando um processo termina inesperadamente. Cada placa usa o sufixo `-gpuN` na pool.
- Eliminadas duas cópias temporárias de 512 MiB na geração das provas de matrizes já alinhadas. Acrescentado um teste de igualdade dos bytes com o caminho original.
- Corrigida a colisão entre o nome de uma variável local CUDA e a declaração global.
- O build de produção utiliza apenas o backend CUDA; o backend CPU fica para testes de desenvolvimento.
- Verificação local de cada prova antes do envio, usando a biblioteca Rust do projeto de base. O build de produção falha se esta biblioteca estiver ausente.
- O processo de teste CPU sem provas está bloqueado contra mineração. Nenhum executável desse teste está incluído.

## Diagnóstico opcional do rig

Para confirmar versão da distribuição, memória RAM, VRAM e bibliotecas, copia apenas `diagnostico.sh` para o rig e executa:

```bash
bash diagnostico.sh
```

O script é só de leitura. Não pára o ForgeMiner nem recolhe a configuração da carteira, chaves privadas ou credenciais do HiveOS. Devolve JSON com os dados técnicos; esse resultado permite confirmar as condições de compilação e de execução.

## Compilar — receitas de reconstrução

A receita Docker compila dentro de Ubuntu 22.04 com CUDA 12.8.1 e Rust 1.90.0. É necessário Docker num computador de desenvolvimento; a compilação não precisa de GPU. Não instalar ferramentas de desenvolvimento no rig só para executar este passo.

Na pasta que contém Dockerfile.build, num terminal Bash:

```bash
mkdir -p dist
docker build -f Dockerfile.build -t prl3060-build:0.1.0 .
docker run --rm -v "$PWD/dist:/export" prl3060-build:0.1.0
```

O build descarrega a imagem NVIDIA, dependências Ubuntu, Rust e CUTLASS v2.11.0. Pode demorar e ocupar vários GB. A receita não foi executada neste ambiente; poderá precisar de correções após a primeira compilação. O ficheiro pretendido no fim é `dist/prl3060-kryptex-0.1.0.tar.gz`.

Esse pacote destina-se a sistemas com glibc >= 2.35 (Ubuntu 22.04 ou mais recente). A tua glibc 2.35 já foi confirmada; ainda falta testar o executável na rig. Um rig com Ubuntu 20.04 precisa de outro ambiente de compilação.

O empacotamento inclui as bibliotecas CUDA necessárias, mas nunca o driver `libcuda.so`. As licenças e avisos dos componentes seguem no pacote. O código completo desta adaptação permanece neste ZIP. O tar.gz terá uma pasta raiz `prl3060-kryptex`, conforme a integração Custom Miner.

## Compilar com GitHub Actions

O pacote inclui o workflow `.github/workflows/build-hiveos.yml`, preparado mas ainda não executado. Arranca automaticamente num push para main que altere o código ou os ficheiros de compilação; também pode ser iniciado manualmente. Para o utilizar, os conteúdos desta pasta têm de estar na raiz de um repositório GitHub, incluindo o workflow. Em **Actions → Build PRL3060 HiveOS (experimental) → Run workflow**, a compilação usa Ubuntu 22.04/CUDA 12.8.1, executa os testes de provas e cria um artefacto `prl3060-kryptex-experimental` com o tar.gz e o seu SHA256. Não publica automaticamente uma release nem altera a rig.

Existe também `scripts/build-local.py`, para Linux com Python 3.12+, CMake, make, curl, git e dpkg-deb. Descarrega componentes oficiais NVIDIA/Rust/Ubuntu, verifica os SHA256 dos manifestos e compila com um sysroot glibc 2.35. Precisa de acesso de rede aos fornecedores; essa receita ficou bloqueada neste ambiente. Não é um instalador para a rig.

## Testar depois de compilar

1. Reserva uma GPU para o ensaio e pára o miner que a estiver a utilizar. Não executes dois miners na mesma placa.
2. Extrai o pacote de runtime numa pasta de teste. Executa `bash selftest.sh 0` nessa pasta. Este teste usa a GPU 0 com dados artificiais e verifica uma prova localmente, sem contactar a pool. Usa matrizes do tamanho de produção e um target artificial fácil. Exige `[mock] PASS: first share built and verified` e saída com código 0.
3. Só depois prepara o ensaio com a Kryptex: copia `config.example.json` para `config.json`, preenche `wallet` com o teu ID Kryptex ou endereço PRL e executa `python3 runner.py`.
4. A configuração de exemplo usa apenas GPU 0. Confirma shares aceites tanto no log como no painel da Kryptex. Em caso de rejeições de prova, pára o teste e guarda o erro.
5. Depois de uma validação inicial, muda `devices` para `[0,1,2,3]`. Com quatro processos, o uso de RAM e CPU durante a construção das provas aumenta; tem de ser medido no rig. Os 4896 MiB disponíveis não garantem, por si só, que as quatro placas possam trabalhar simultaneamente.
6. Compara um período suficientemente longo com o ForgeMiner, usando os mesmos clocks e power limits: shares/dificuldade, taxa efetiva na pool, rejeições, energia e estabilidade. O valor local de TH/s não substitui esta comparação.

## Campos previstos no HiveOS, após validação

| Campo | Valor |
|---|---|
| Coin | PRL |
| Miner | Custom |
| Miner name | prl3060-kryptex |
| Wallet and worker template | `%WAL%/%WORKER_NAME%` |
| Pool URL | `stratum+tcp://prl.kryptex.network:7048` |
| Pass | `x` |
| Extra config, primeiro ensaio | `--devices 0` |
| Extra config, quatro placas | `--devices 0,1,2,3` |

O campo Installation URL requer um endereço HTTPS para o **tar.gz compilado**. Este ZIP de código-fonte e um link `sandbox:` não servem nesse campo. Não foi publicado um URL de instalação. Em alternativa, um pacote compilado pode ser transferido manualmente para o rig; a instalação deve ser feita apenas depois dos testes acima.

O hashrate do painel é calculado a partir dos intervalos de trabalho reportados pelo motor. A conversão é 1 TH/s = 10^12 H/s = 10^9 kH/s. Estatísticas antigas ou de processos desligados são apresentadas com hashrate zero. Uma leitura positiva não prova que a pool está a aceitar as provas.

## Testes de desenvolvimento

```bash
python3 tests/test_runtime.py
bash -n hiveos/h-config.sh hiveos/h-run.sh hiveos/h-stats.sh hiveos/selftest.sh scripts/package.sh diagnostico.sh
```

O ensaio C++ `tests/test_pool.cpp` usa um servidor em localhost com dados fictícios. Não faz mineração nem contacta a Kryptex. O script `scripts/test-host.sh` compila-o e executa os testes sem CUDA; os artefactos de teste nunca devem ser distribuídos como runtime.

## Fontes e licenças

- CPPminer: https://github.com/1640675651/CPPminer (MIT, foolzhz; commit em UPSTREAM.txt).
- Rede Pearl: https://github.com/pearl-research-labs/pearl.
- Endereços e configuração da pool: https://pool.kryptex.com/prl.
- Integração Custom Miner: https://hiveon.com/forum/t/custom-miner-integration/4521.
- JSON for Modern C++ 3.11.3: https://github.com/nlohmann/json (MIT).
- BLAKE3 1.8.5 e bibliotecas Pearl/Plonky2: avisos preservados nas respetivas pastas `engine/third_party`.
- NVIDIA CUTLASS: https://github.com/NVIDIA/cutlass (BSD-3-Clause).

A licença MIT do projeto de base está em `engine/LICENSE`. Os novos ficheiros de integração seguem também a licença MIT, em LICENSE. Não há garantia de desempenho, compatibilidade com alterações futuras da rede ou aceitação de shares.
