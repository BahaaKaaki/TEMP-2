FROM python:3.12-slim

RUN groupadd -g 1000 sandbox && useradd -u 1000 -g sandbox -m sandbox

RUN pip install --no-cache-dir \
    pandas \
    numpy \
    matplotlib \
    scipy \
    scikit-learn \
    openpyxl \
    xlsxwriter \
    python-pptx \
    PyMuPDF \
    cloudpickle

COPY agent_studio /usr/local/lib/python3.12/site-packages/agent_studio
COPY sandbox_server.py /opt/sandbox_server.py

RUN mkdir -p /workspace /outputs && \
    chown sandbox:sandbox /workspace /outputs

EXPOSE 443
WORKDIR /workspace

CMD ["python", "/opt/sandbox_server.py"]
