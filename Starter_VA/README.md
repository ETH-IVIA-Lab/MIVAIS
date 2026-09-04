# Starter VA

A small useful mixed-initiative VA system built on MIVAIS: one
scatterplot, one agent, one config file, no build step.

The analyst picks two attributes of a small car dataset; the `InsightAgent`
watches that selection and - unprompted - writes a correlation insight into
the shared World State and comments in the chat. Human acts - agent observes -
agent acts - human sees it: mixed-initiative VA in miniature.

This app is the running example of the **step-by-step tutorial served at
`/setup` on MIVAIS Studio**, which walks from an empty folder to this system
and then to running a controlled user study on it. Start there.

## Run it

```bash
cd Starter_VA/backend
pip install -r requirements.txt   # installs ../../MIVAIS editably
python main.py                    # → http://127.0.0.1:7300
```

Open two browser tabs (one with `?role=observer`) to see the real-time sync.

## Layout

```
Starter_VA/
├── backend/
│   ├── main.py               # all wiring: infrastructure, gateway, endpoints
│   ├── agents_config.yaml    # who may do what (users + agents, one vocabulary)
│   ├── agents/
│   │   └── insight_agent.py  # the one software agent
│   └── requirements.txt
└── frontend/
    └── index.html            # one file, vanilla JS + SVG
```
