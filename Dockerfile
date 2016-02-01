FROM matsengrp/cpp

# Java bit copied from https://github.com/jplock/docker-oracle-java7
RUN sed 's/main$/main universe/' -i /etc/apt/sources.list;exit 0
RUN apt-get update && apt-get install -y software-properties-common python-software-properties;exit 0
RUN add-apt-repository ppa:webupd8team/java -y; exit 0
RUN apt-get update; exit 0
RUN echo oracle-java7-installer shared/accepted-oracle-license-v1-1 select true | /usr/bin/debconf-set-selections; exit 0
RUN apt-get install -y \
    astyle \
    oracle-java7-installer \
    libgsl0ldbl \
    libgsl0-dev \
    libncurses5-dev \
    libxml2-dev \
    libxslt1-dev \
    python-scipy \
    python-sklearn \
    r-base \
    zlib1g-dev; exit 0
RUN pip install \
    beautifulsoup4 \
    biopython \
    cython \
    decorator \
    dendropy==3.12.3 \
    lxml \
    networkx \
    pysam \
    pyyaml \
    seaborn; exit 0
RUN R --vanilla --slave -e 'install.packages("TreeSim", repos="http://cran.rstudio.com/")'; exit 0


COPY . /partis
WORKDIR /partis
CMD ./bin/build.sh && export $PWD/packages/samtools; exit 0
