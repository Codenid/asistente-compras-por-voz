# Notebooks

## Crear entorno

    ~/.pyenv/versions/3.11.9/bin/python -m venv .venv-asistente-voz
    source .venv-asistente-voz/bin/activate
    python --version

## Abrir JupyterLab

Desde la raíz del proyecto:

    ./scripts/start_notebook.sh

El kernel quedará asociado al entorno `.venv-asistente-voz`, por lo que las
importaciones y paquetes se ejecutan dentro de ese entorno. Para abrir otro
entorno Python (incluido uno con PyTorch/CUDA), registra su kernel así:

    ./scripts/register_python_kernel.sh /ruta/a/tu/entorno "Python CUDA"
    PYTHON_ENV=/ruta/a/tu/entorno ./scripts/start_notebook.sh

Dentro del notebook puedes comprobar CUDA con:

    import torch
    print(torch.cuda.is_available())
    print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CUDA no disponible")

Espacio permanente para exploración interactiva.

Convención sugerida:

```text
01_rag_exploration.ipynb
02_voice_provider_test.ipynb
03_agent_prompts.ipynb
```

Mantén aquí experimentos que ayuden a tomar decisiones técnicas. Cuando una prueba se estabilice, mueve la lógica reutilizable a `app/` y deja una prueba automatizada en `tests/`.
