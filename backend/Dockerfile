FROM python:3.11-slim

WORKDIR /app

# System dependencies (for lxml and Pillow)
RUN apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt1-dev \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    ffmpeg \
    libreoffice-impress \
    libreoffice-writer \
    default-jre-headless \
    poppler-utils \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    fonts-inter \
    fonts-lato \
    fonts-montserrat \
    fonts-open-sans \
    fonts-roboto \
    fonts-manrope \
    fonts-quicksand \
    fonts-adobe-sourcesans3 \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Register Calibri → Carlito font substitution for LibreOffice
RUN mkdir -p /usr/lib/libreoffice/share/registry && \
    printf '<?xml version="1.0" encoding="UTF-8"?>\n<oor:component-data xmlns:oor="http://openoffice.org/2001/registry" oor:name="Substitutions" oor:package="org.openoffice.VCL">\n<node oor:name="FontSubstitutions">\n<node oor:name="Calibri" oor:op="fuse">\n<prop oor:name="FontSubstitutes"><value>Carlito;Liberation Sans</value></prop>\n</node>\n</node>\n</oor:component-data>' > /usr/lib/libreoffice/share/registry/calibri-substitution.xcu

# Poppins is not packaged for Debian - vendored as OFL-licensed static weights
# (AI slide generators use it a lot, see assets/fonts/poppins/OFL.txt for the license).
COPY assets/fonts/poppins/*.ttf /usr/share/fonts/truetype/poppins/
RUN fc-cache -f

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY entrypoint.sh /usr/local/bin/askf-entrypoint.sh
RUN chmod +x /usr/local/bin/askf-entrypoint.sh

EXPOSE 8000

# Starts through the script so the process count comes from the available cores
# instead of being fixed. The switch for that sits at the top of the script and is
# off today, so exactly one process runs as before. The Celery containers override
# this via 'command:' in the compose file.
CMD ["/usr/local/bin/askf-entrypoint.sh"]
