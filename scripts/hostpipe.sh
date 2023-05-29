#!/bin/bash

LOGFILE=/var/log/hostpipe.log

while true; do
  PIPE=/opt/fieldedge/pipe
  if read line <${PIPE}; then
    DATEFMT="$(date -u +'%Y-%m-%dT%H:%M:%S.%3NZ')"
    CMDFMT="${DATEFMT},[INFO],command="
    RESFMT="${DATEFMT},[INFO],result="
    echo "${CMDFMT}${line}" \
      >>${LOGFILE}
    eval "${line}" 2>&1 \
      | sed -e "s/^/${RESFMT}/" \
      >>${LOGFILE}
  fi
done