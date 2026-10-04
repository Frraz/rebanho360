"""Gunicorn do contêiner `web` (lido de /app/gunicorn.conf.py).

Dimensionado para o limite de 2,3 GB do serviço em `docker-compose.prod.yml`:
cada worker Django carrega ~150–250 MB, então 9 workers cabem com folga e as
telas de dashboard, que gastam CPU em Python, rodam em paralelo (thread não
paraleliza CPU por causa do GIL; worker sim). As duas threads por worker cobrem
a espera por banco e por rede.

Tudo se ajusta por variável de ambiente, sem refazer a imagem.
"""

import os

bind = "0.0.0.0:8000"

workers = int(os.environ.get("WEB_CONCURRENCY", "9"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "2"))

timeout = 60
graceful_timeout = 30
keepalive = 5

# Recicla o worker depois de N requisições (com folga aleatória, para não
# reiniciarem todos juntos): contém vazamento lento de memória em processo longo.
max_requests = 1000
max_requests_jitter = 100

# O arquivo de heartbeat do worker em memória: com disco do contêiner lento, o
# gunicorn chega a matar worker saudável por falta de heartbeat.
worker_tmp_dir = "/dev/shm"

# Carrega o código uma vez e divide as páginas de memória entre os workers
# (copy-on-write): menos memória por worker.
preload_app = True
