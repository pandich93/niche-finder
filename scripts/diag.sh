#!/usr/bin/env sh
# Диагностика связки niche-finder <-> YouTube Data API.
# Запуск:  sh ~/Desktop/projects/youtube/analytic/scripts/diag.sh
# Результат пишется в scripts/diag-output.txt (ключ API маскируется).
DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT="$DIR/scripts/diag-output.txt"
KEY=$(grep -E '^YOUTUBE_API_KEY' "$DIR/.env" | sed -E 's/^[^=]+=//; s/"//g' | tr -d '\r ')
{
  echo "=== 1. date ==="; date
  echo; echo "=== 2. docker ps ==="
  docker ps --format '{{.Names}}  {{.Status}}' 2>&1
  echo; echo "=== 3. ключ (маска) ==="
  echo "len=${#KEY} prefix=$(echo "$KEY" | cut -c1-8)"
  echo; echo "=== 4. videoCategories.list с ХОСТА (macOS) ==="
  curl -sS -m 20 -w "\nhttp=%{http_code} time=%{time_total}\n" \
    "https://www.googleapis.com/youtube/v3/videoCategories?part=snippet&regionCode=US&key=$KEY" \
    2>&1 | sed "s/$KEY/***KEY***/g" | head -c 1200
  echo; echo "=== 5. search.list с ХОСТА (тратит 1 из 100/день) ==="
  curl -sS -m 20 -w "\nhttp=%{http_code} time=%{time_total}\n" \
    "https://www.googleapis.com/youtube/v3/search?part=snippet&q=test&type=video&maxResults=1&key=$KEY" \
    2>&1 | sed "s/$KEY/***KEY***/g" | head -c 1200
  echo; echo "=== 6. тот же вызов ИЗНУТРИ контейнера niche-finder ==="
  # -e NICHE_DATABASE_URL= гасит хостовый DSN из .env (localhost:5433):
  # внутри контейнера база доступна только как postgres:5432.
  docker run --rm --network niche-finder_default --env-file "$DIR/.env" \
    -e NICHE_DATABASE_URL= \
    -v "$DIR/backend:/app:ro" -v niche-finder-models:/models niche-finder:latest \
    python -c "
import os,time,requests
k=os.environ.get('YOUTUBE_API_KEY','')
print('key len in container:',len(k))
t=time.time()
try:
    r=requests.get('https://www.googleapis.com/youtube/v3/videoCategories',
                   params={'part':'snippet','regionCode':'US','key':k},timeout=25)
    print('status',r.status_code,'in %.1fs'%(time.time()-t))
    print(r.text[:600].replace(k,'***KEY***') if k else r.text[:600])
except Exception as e:
    print('EXC after %.1fs:'%(time.time()-t), type(e).__name__, str(e)[:400])
" 2>&1 | sed "s/$KEY/***KEY***/g" | head -c 1500
  echo; echo "=== 7. cli.py doctor ==="
  docker run --rm --network niche-finder_default --env-file "$DIR/.env" \
    -e NICHE_DATABASE_URL= \
    -e POSTGRES_HOST=postgres -v "$DIR/backend:/app:ro" -v niche-finder-models:/models \
    niche-finder:latest python cli.py doctor 2>&1 | sed "s/$KEY/***KEY***/g" | head -c 1500
  echo; echo "=== 8. последние логи worker ==="
  docker logs --tail 40 niche-finder-worker 2>&1 | sed "s/$KEY/***KEY***/g" | head -c 2000
  echo; echo "=== КОНЕЦ ==="
} > "$OUT" 2>&1
echo "Готово. Результат: $OUT"
