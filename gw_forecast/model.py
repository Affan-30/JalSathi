"""
Step 3 - the network.

  last <=12 readings (change, depth, age, season, valid) -> LSTM ─┐
  static traits (location, well depth, aquifer, well type) -> MLP ┼-> MLP head -> [P10, P50, P90] of
  query (days ahead, season now/target) + rain features --------- ┘    "level in h days minus latest reading"

Irregular spacing is handled by feeding each reading's AGE as an input - no resampling, no gap filling.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
from config import CFG
from features import N_TOK, N_STATIC, N_CTX


class GWNet(nn.Module):
    def __init__(self, hidden=None, layers=None, dropout=None):
        super().__init__()
        hidden, layers = hidden or CFG.hidden, layers or CFG.layers
        dropout = CFG.dropout if dropout is None else dropout
        self.lstm = nn.LSTM(N_TOK, hidden, layers, batch_first=True, dropout=dropout if layers > 1 else 0)
        self.side = nn.Sequential(nn.Linear(N_STATIC + N_CTX, 64), nn.ReLU())
        self.head = nn.Sequential(nn.Linear(hidden + 64, 128), nn.ReLU(), nn.Dropout(dropout), nn.Linear(128, 3))

    def forward(self, tok, static, ctx):
        out, _ = self.lstm(tok)
        y = self.head(torch.cat([out[:, -1], self.side(torch.cat([static, ctx], 1))], 1))
        mid = y[:, 0]
        return torch.stack([mid - F.softplus(y[:, 1]), mid, mid + F.softplus(y[:, 2])], 1)   # non-crossing quantiles


def pinball(pred, y, qs=CFG.quantiles):
    q = torch.tensor(qs, device=pred.device).view(1, -1)
    e = y.unsqueeze(1) - pred
    return torch.maximum(q * e, (q - 1) * e).mean()
