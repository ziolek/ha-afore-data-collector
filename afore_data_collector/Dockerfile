ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-paho-mqtt

WORKDIR /app
COPY collector.py /app/collector.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
