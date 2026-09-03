# experiments/

Arnês de experimento (passo 2.5 do plano de desenvolvimento).

Recebe como parâmetros o número de eventos por execução, o perfil de funil, o
número de repetições e a semente pseudoaleatória; executa os cenários; e grava
o resultado em `../data/`.

Requisito metodológico: a geração dos eventos é probabilística e reprodutível.
A mesma semente deve produzir exatamente o mesmo conjunto de eventos. Os
parâmetros das distribuições (probabilidades condicionais do funil, taxa do
processo de Poisson, parâmetros da log-normal do atraso) são declarados aqui e
descritos na seção Material e Métodos do TCC.

Ainda não implementado.
