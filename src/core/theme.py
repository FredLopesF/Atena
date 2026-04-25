"""MyRD Design System — "Retro Circuit" theme.

Paleta inspirada em hardware de arcade, PCBs e monitores CRT vintage.
Accent: verde-fósforo (#39D98A) — referência a monitores Phosphor Green.

60/30/10 rule:
    60% → Background system (deep/surface/raised)
    30% → Content (texto, borders)
    10% → Accent (CTAs, seleção, highlights)
"""

# ---------------------------------------------------------------------------
# Background System (60%)
# ---------------------------------------------------------------------------

BG_DEEP = "#0D0F14"       # Fundo principal da janela
BG_SURFACE = "#151820"    # Painéis, cards, game list
BG_RAISED = "#1C2030"     # Top/filter/bottom bars, modals
BG_BORDER = "#2A3045"     # Bordas sutis entre seções

# ---------------------------------------------------------------------------
# Content Colors (30%)
# ---------------------------------------------------------------------------

TEXT_PRIMARY = "#E8EAF0"   # Texto principal, labels
TEXT_SECONDARY = "#8A93A8" # Labels secundários, placeholders
TEXT_MUTED = "#556070"     # Metadata (tamanho de arquivo, regiões)

# ---------------------------------------------------------------------------
# Accent — Verde Fósforo (10%)
# ---------------------------------------------------------------------------

ACCENT_PRIMARY = "#39D98A"  # CTAs: Baixar Jogos, salvar
ACCENT_HOVER = "#2EC77A"    # Hover state do accent
ACCENT_DIM = "#1A3A2A"      # Fundo de linha selecionada

# ---------------------------------------------------------------------------
# Semantic Colors
# ---------------------------------------------------------------------------

COLOR_DANGER = "#E05252"    # Destrutivo: Cancelar, Limpar Histórico
COLOR_DANGER_DIM = "#3A1A1A"# Hover sutil para danger
COLOR_WARNING = "#F59E0B"   # Avisos, loading states
COLOR_INFO = "#3B9FE8"      # Informações, links
COLOR_SUCCESS = ACCENT_PRIMARY

# ---------------------------------------------------------------------------
# Game List
# ---------------------------------------------------------------------------

LIST_ROW_A = "#14171F"      # Linha par
LIST_ROW_B = "#191D28"      # Linha ímpar (contraste mais pronunciado)
LIST_ROW_HOVER = "#1F2535"  # Hover state de linha
LIST_ROW_SELECTED_BG = ACCENT_DIM
LIST_ROW_SELECTED_BORDER = ACCENT_PRIMARY

# ---------------------------------------------------------------------------
# Status Log Tags
# ---------------------------------------------------------------------------

STATUS_COLOR_NORMAL = TEXT_PRIMARY
STATUS_COLOR_ERROR = COLOR_DANGER
STATUS_COLOR_LOADING = COLOR_WARNING
STATUS_COLOR_SUCCESS = ACCENT_PRIMARY

# ---------------------------------------------------------------------------
# Typography
# Nota: CustomTkinter em Windows usa "Segoe UI" como fallback ideal.
# JetBrains Mono para elementos terminal-like (status log, metadata).
# ---------------------------------------------------------------------------

FONT_FAMILY_UI = "Segoe UI"        # Interface principal
FONT_FAMILY_MONO = "Consolas"      # Status log, timestamps, file sizes

FONT_SIZE_XS = 10   # Metadata secundária
FONT_SIZE_SM = 11   # Timestamps, tooltips
FONT_SIZE_MD = 12   # Labels, filtros
FONT_SIZE_LG = 13   # Botões, list items
FONT_SIZE_XL = 14   # Título de seção, headers de modal

# ---------------------------------------------------------------------------
# Spacing (multiples of 4)
# ---------------------------------------------------------------------------

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24

# ---------------------------------------------------------------------------
# Component Heights
# ---------------------------------------------------------------------------

HEIGHT_BTN_PRIMARY = 38    # Botão de ação primária (Baixar Jogos)
HEIGHT_BTN_SECONDARY = 34  # Botões secundários
HEIGHT_BTN_SM = 30         # Botões pequenos (filtros)
HEIGHT_INPUT = 34          # Inputs e combos
HEIGHT_LIST_ROW = 32       # Altura de linha da game list

# ---------------------------------------------------------------------------
# Corner Radius
# Mantendo linguagem sharp/clean — corner_radius=0 é intencional.
# Usar 4 apenas em checkboxes e elementos pequenos.
# ---------------------------------------------------------------------------

RADIUS_NONE = 0
RADIUS_SM = 4
RADIUS_MD = 8

# ---------------------------------------------------------------------------
# Card Grid
# ---------------------------------------------------------------------------

CARD_WIDTH = 185
CARD_IMG_HEIGHT = 110
CARD_BG = BG_SURFACE
CARD_BG_HOVER = "#1E2235"
CARD_BG_SELECTED = ACCENT_DIM
CARD_BADGE_BG = "#2A3550"
CARD_BADGE_TEXT = TEXT_PRIMARY
CARD_CHECK_COLOR = ACCENT_PRIMARY

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

SIDEBAR_WIDTH = 240
SIDEBAR_BG = BG_RAISED
