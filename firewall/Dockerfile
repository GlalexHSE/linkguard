FROM alpine:3.21
RUN apk add --no-cache iptables
COPY fw.sh rules.conf /fw/
ENTRYPOINT ["/bin/sh", "/fw/fw.sh"]
CMD ["show"]
