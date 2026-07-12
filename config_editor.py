"""
config_editor.py

Generic parser/serializer for PalWorldSettings.ini. Palworld stores nearly
all of its server settings on a single line inside a Python/UE-style
tuple-looking string:

    [/Script/Pal.PalGameWorldSettings]
    OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,...,PublicPort=8211,...)

Rather than hardcoding every one of Palworld's ~90 settings (which
changes between game versions), this parses whatever keys are present
into an ordered dict, so the editor stays "full" / future-proof even
after Palworld adds new settings in later patches. Values keep their
original type hints (bool / number / quoted string) so we can generate
sensible widgets and write the file back out losslessly.
"""

import re
from collections import OrderedDict
from pathlib import Path

OPTION_LINE_RE = re.compile(r'^(OptionSettings\s*=\s*)\((.*)\)\s*$')

DEFAULT_INI_TEMPLATE = """[/Script/Pal.PalGameWorldSettings]
OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,NightTimeSpeedRate=1.000000,ExpRate=1.000000,PalCaptureRate=1.000000,PalSpawnNumRate=1.000000,PalDamageRateAttack=1.000000,PalDamageRateDefense=1.000000,PlayerDamageRateAttack=1.000000,PlayerDamageRateDefense=1.000000,PlayerStomachDecreaceRate=1.000000,PlayerStaminaDecreaceRate=1.000000,PlayerAutoHPRegeneRate=1.000000,PlayerAutoHpRegeneRateInSleep=1.000000,PalStomachDecreaceRate=1.000000,PalStaminaDecreaceRate=1.000000,PalAutoHPRegeneRate=1.000000,PalAutoHpRegeneRateInSleep=1.000000,BuildObjectDamageRate=1.000000,BuildObjectDeteriorationDamageRate=1.000000,CollectionDropRate=1.000000,CollectionObjectHpRate=1.000000,CollectionObjectRespawnSpeedRate=1.000000,EnemyDropItemRate=1.000000,DeathPenalty=All,bEnableFriendlyFire=False,bEnableInvaderEnemy=True,bActiveUNKO=False,bEnableAimAssistPad=True,bEnableAimAssistKeyboard=False,DropItemMaxNum=3000,DropItemMaxNum_UNKO=100,BaseCampMaxNum=128,BaseCampWorkerMaxNum=15,DropItemAliveMaxHours=1.000000,bAutoResetGuildNoOnlinePlayers=False,AutoResetGuildTimeNoOnlinePlayers=72.000000,GuildPlayerMaxNum=20,PalEggDefaultHatchingTime=72.000000,WorkSpeedRate=1.000000,bIsMultiplay=False,bIsPvP=False,bCanPickupOtherGuildDeathPenaltyDrop=False,bEnableNonLoginPenalty=True,bEnableFastTravel=True,bIsStartLocationSelectByMap=True,bExistPlayerAfterLogout=False,bEnableDefenseOtherGuildPlayer=False,CoopPlayerMaxNum=4,ServerPlayerMaxNum=32,ServerName="Default Palworld Server",ServerDescription="",AdminPassword="",ServerPassword="",PublicPort=8211,PublicIP="",RCONEnabled=False,RCONPort=25575,Region="",bUseAuth=True,BanListURL="https://api.palworldgame.com/api/banlist.txt")
"""


def parse_kv_string(inner: str) -> "OrderedDict[str, str]":
    """
    Split the comma-separated key=value string, respecting quoted values
    (so commas or '=' inside quotes don't break the split).
    """
    pairs = OrderedDict()
    current = []
    tokens = []
    in_quotes = False
    for ch in inner:
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
        elif ch == ',' and not in_quotes:
            tokens.append(''.join(current))
            current = []
        else:
            current.append(ch)
    if current:
        tokens.append(''.join(current))

    for tok in tokens:
        tok = tok.strip()
        if not tok or '=' not in tok:
            continue
        key, value = tok.split('=', 1)
        pairs[key.strip()] = value.strip()
    return pairs


def serialize_kv(pairs: "OrderedDict[str, str]") -> str:
    return ','.join(f"{k}={v}" for k, v in pairs.items())


def classify_value(value: str) -> str:
    """Returns 'bool' | 'number' | 'string' for widget selection."""
    if value in ("True", "False"):
        return "bool"
    if re.match(r'^-?\d+(\.\d+)?$', value):
        return "number"
    return "string"


def format_value(raw_value: str, new_value: str) -> str:
    """Re-wrap new_value the same way the original was formatted (quotes etc)."""
    kind = classify_value(raw_value)
    if kind == "string":
        v = new_value.strip()
        if v.startswith('"') and v.endswith('"'):
            return v
        return f'"{v}"'
    return new_value.strip()


class PalConfig:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.raw_text = ""
        self.prefix = "OptionSettings="
        self.pairs: "OrderedDict[str, str]" = OrderedDict()
        self._line_index = None
        self._lines = []

    def exists(self):
        return self.path.exists()

    def create_default(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(DEFAULT_INI_TEMPLATE, encoding="utf-8")

    def load(self):
        if not self.path.exists():
            self.create_default()
        self.raw_text = self.path.read_text(encoding="utf-8", errors="ignore")
        lines = self.raw_text.splitlines()
        for i, line in enumerate(lines):
            m = OPTION_LINE_RE.match(line.strip())
            if m:
                self.prefix = m.group(1)
                self.pairs = parse_kv_string(m.group(2))
                self._line_index = i
                break
        if self._line_index is None:
            raise ValueError("Could not find OptionSettings=(...) line in ini file.")
        self._lines = lines

    def save(self, updated_pairs: "OrderedDict[str, str]"):
        new_line = f"{self.prefix}({serialize_kv(updated_pairs)})"
        self._lines[self._line_index] = new_line
        self.path.write_text("\n".join(self._lines) + "\n", encoding="utf-8")
        self.pairs = updated_pairs

    def get_port(self, key="PublicPort", default=8211):
        try:
            return int(self.pairs.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key, default=False):
        return self.pairs.get(key, str(default)) == "True"
