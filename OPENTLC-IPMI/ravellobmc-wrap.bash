#!/bin/bash

# need to wait here until cloud-init does it's thing, usually around 10 seconds.
echo "Waiting for cloud-init to finish startup"
sleep 15

CONF=/etc/ravellobmc/ravellobmc.conf

if [ -f $CONF ]
then
	source $CONF
else
	echo "Error: File $CONF not found."
	exit 1
fi

CMD="/usr/local/bin/ravellobmc-wrap.rb"
ephTok=${ephTok} CMD=${CMD} /usr/bin/scl enable ruby200 '$CMD $ephTok'

