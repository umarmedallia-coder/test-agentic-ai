FROM alpine:latest

RUN apk add --no-cache \
	bash \
	bash-completion \
	ca-certificates \
	curl \
	git \
	git-bash-completion \
	less \
	openssh-client-default \
	&& printf '%s\n' \
		'if [ -f /usr/share/bash-completion/bash_completion ]; then' \
		'  . /usr/share/bash-completion/bash_completion' \
		'fi' \
		> /root/.bashrc

WORKDIR /workspace
CMD ["/bin/bash"]