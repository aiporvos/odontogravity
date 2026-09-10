#!/usr/bin/env bash
# Backup diario de la base de Silprodent.
#
# Se instala en el VPS con cron. Perder el volumen de Postgres significaba
# perder pacientes, turnos, odontogramas e historial de conversaciones sin
# ninguna forma de recuperarlos: el docker-compose usa un volumen local y no
# habia ningun pg_dump corriendo.
#
#   crontab -e
#   15 3 * * * /root/backup_silprodent.sh >> /var/log/backup-silprodent.log 2>&1
#
# Guarda 30 dias. Un dump comprimido de esta base pesa ~300 KB, asi que un mes
# entero ocupa menos de 10 MB.
set -euo pipefail

CONTENEDOR="${CONTENEDOR:-aiporvos-odontogravity-d4adwp-db-1}"
BASE="${BASE:-dentibot}"
USUARIO="${USUARIO:-dentibot}"
DESTINO="${DESTINO:-/root/backups/silprodent}"
RETENER_DIAS="${RETENER_DIAS:-30}"

mkdir -p "$DESTINO"
FECHA=$(date +%Y%m%d-%H%M)
ARCHIVO="$DESTINO/dentibot-$FECHA.dump"

echo "[$(date '+%F %T')] Iniciando backup de $BASE"

# --format=custom permite restaurar tablas sueltas y ya viene comprimido.
docker exec "$CONTENEDOR" pg_dump -U "$USUARIO" -d "$BASE" \
    --format=custom --no-owner --no-privileges > "$ARCHIVO"

# Un archivo vacio o minusculo no es un backup: mejor fallar ruidosamente.
TAMANO=$(stat -c%s "$ARCHIVO")
if [ "$TAMANO" -lt 10000 ]; then
    echo "[$(date '+%F %T')] ❌ El dump pesa $TAMANO bytes: algo salió mal"
    rm -f "$ARCHIVO"
    exit 1
fi

# Que el archivo se pueda LEER, no solo que exista. Un dump corrupto pasa
# desapercibido hasta el dia que hace falta.
if ! docker exec -i "$CONTENEDOR" pg_restore --list < "$ARCHIVO" > /dev/null 2>&1; then
    echo "[$(date '+%F %T')] ❌ El dump no se puede leer: se descarta"
    rm -f "$ARCHIVO"
    exit 1
fi

echo "[$(date '+%F %T')] ✅ $ARCHIVO ($(numfmt --to=iec "$TAMANO"))"

BORRADOS=$(find "$DESTINO" -name 'dentibot-*.dump' -mtime "+$RETENER_DIAS" -print -delete | wc -l)
[ "$BORRADOS" -gt 0 ] && echo "[$(date '+%F %T')] Borrados $BORRADOS backups de más de $RETENER_DIAS días"

echo "[$(date '+%F %T')] Backups guardados: $(find "$DESTINO" -name 'dentibot-*.dump' | wc -l)"
