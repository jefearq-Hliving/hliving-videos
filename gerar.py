# Gera as versões leves (para o WhatsApp) dos vídeos do Portal do Corretor.
# Lê a lista de vídeos do portal (index.html do hliving-dashboard + vídeos incluídos pelo Admin),
# reaproveita os que já estão publicados e, para os novos, baixa o original do Drive e comprime.
# Resultado em ./site: <id do Drive>.mp4 + lista.json, publicado no GitHub Pages.
import json, os, re, shutil, subprocess, sys, urllib.request

PORTAL = os.environ.get("PORTAL", "https://raw.githubusercontent.com/jefearq-Hliving/hliving-dashboard/main/index.html")
KV = os.environ.get("KV", "https://hliving-portal.bold-resonance-24f8.workers.dev/?action=getPortal")
SITE_URL = os.environ.get("SITE_URL", "https://jefearq-hliving.github.io/hliving-videos/")
DRIVE = os.environ.get("DRIVE", "https://drive.usercontent.google.com/download?id={}&export=download&confirm=t")
SAIDA = os.environ.get("SAIDA", "site")
TMP = os.environ.get("TMP_DIR", "tmp")
TETO_MB = 25          # tamanho máximo de cada vídeo leve
JA_LEVE_MB = 20       # H.264 até 1280 px e abaixo disto: só reorganiza o arquivo, sem recomprimir
LADO = 1280           # lado maior (720p)
ID = re.compile(r"[A-Za-z0-9_-]{20,80}")
# atalhos do Drive usados no portal -> arquivo de verdade (o download do atalho não funciona)
ATALHOS = {
    "1MGSbEy0x1wL6-x6zssTQ-YYzMIGuGlfy": "1bQ5WIUkePy5CwQPnZ62e5BulxpH1G-9T",  # Atlantia: filme com localização
    "1MVrTIV3JlJeqadxmd1_NrzKZJpmeSjCy": "1Rt3xsaLS0CbsTiyK0glX7-yUq1hrf4QW",  # Atlantia: filme institucional
    "1qyu_PjzMPszOBiSVVeEc2Y4kQKsWg4gh": "1Gu_EatzMogl_c-QbzYskq59kDto8BiXo",  # Lafayette pronto
    "17E7tha5cQg53Ten2NLxqPZSSf4pgrppB": "1V6sEPrS7iXDlqw79bDPdx2ZncuLMKhPr",  # Lafayette decorado
}


def abre(u, timeout=60):
    if "://" not in u:
        return open(u, "rb").read()
    req = urllib.request.Request(u, headers={"User-Agent": "hliving-videos"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def argumentos(s, i):
    """argumentos de uma chamada M(...) a partir do índice logo após o "(" (respeita strings e colchetes)"""
    args, atual, nivel, aspas = [], [], 1, None
    while i < len(s):
        c = s[i]
        if aspas:
            atual.append(c)
            if c == "\\":
                atual.append(s[i + 1]); i += 1
            elif c == aspas:
                aspas = None
        elif c in "\"'":
            aspas = c; atual.append(c)
        elif c in "([{":
            nivel += 1; atual.append(c)
        elif c in ")]}":
            nivel -= 1
            if nivel == 0:
                args.append("".join(atual)); return args
            atual.append(c)
        elif c == "," and nivel == 1:
            args.append("".join(atual)); atual = []
        else:
            atual.append(c)
        i += 1
    return args


def videos_do_portal():
    html = abre(PORTAL).decode("utf-8")
    achados = {}
    for m in re.finditer(r"\bM\(", html):            # M(capa, fotos, videos, plantas, docs, unidades)
        a = argumentos(html, m.end())
        if len(a) >= 3:
            for i, t in re.findall(r'"([A-Za-z0-9_-]{20,80})\|((?:[^"\\]|\\.)*)"', a[2]):
                achados.setdefault(i, json.loads('"' + t + '"'))
    try:                                               # vídeos incluídos pelo Admin do portal
        d = json.loads(abre(KV, 30))
        for dev in (d.get("devs") or {}).values():
            for s in ((dev or {}).get("add") or {}).get("videos") or []:
                if isinstance(s, str) and "|" in s:
                    i, t = s.split("|", 1)
                    if ID.fullmatch(i):
                        achados.setdefault(i, t)
    except Exception as e:
        print("aviso: não consegui ler os vídeos do Admin:", e)
    return {i: t for i, t in achados.items() if "zip" not in t.lower()}


def sonda(arq):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=codec_type,codec_name,width,height,pix_fmt,color_transfer",
                        "-of", "json", arq], capture_output=True, text=True)
    if r.returncode:
        return None
    j = json.loads(r.stdout)
    v = [s for s in j.get("streams", []) if s.get("codec_type") == "video"]
    if not v:
        return None
    a = [s for s in j.get("streams", []) if s.get("codec_type") == "audio"]
    return {"v": v[0], "a": a[0] if a else None, "dur": float(j.get("format", {}).get("duration") or 0)}


def mb(arq):
    return os.path.getsize(arq) / 1e6


def ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args)
    return r.returncode == 0


def comprime(orig, dest, info, fator=1.0):
    v, dur = info["v"], max(info["dur"], 1.0)
    # bitrate de vídeo para caber no teto (com folga), entre 300k e 1600k
    kbps = int(max(300, min(1600, (TETO_MB * 0.9 * 8000 / dur - 96) * fator)))
    filtros = []
    if v.get("color_transfer") in ("arib-std-b67", "smpte2084"):   # HDR do iPhone -> cores normais
        filtros.append("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                       "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv")
    filtros.append(f"scale='if(gte(iw,ih),trunc(min({LADO},iw)/2)*2,-2)':'if(gte(iw,ih),-2,trunc(min({LADO},ih)/2)*2)'")
    filtros.append("format=yuv420p")
    args = ["-i", orig, "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1",
            "-vf", ",".join(filtros), "-fpsmax", "30",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(26 if fator == 1.0 else 30),
            "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k", "-profile:v", "high",
            "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-movflags", "+faststart", dest]
    return ffmpeg(args)


def gera(orig, dest):
    info = sonda(orig)
    if not info:
        return "não é um vídeo (o arquivo do Drive está público?)"
    v, a = info["v"], info["a"]
    ja_leve = (mb(orig) <= JA_LEVE_MB and v.get("codec_name") == "h264" and v.get("pix_fmt") == "yuv420p"
               and max(v.get("width") or 9999, v.get("height") or 9999) <= 1920
               and (a is None or a.get("codec_name") == "aac"))
    if ja_leve and ffmpeg(["-i", orig, "-map", "0:v:0", "-map", "0:a:0?", "-map_metadata", "-1",
                           "-c", "copy", "-movflags", "+faststart", dest]):
        return None
    if not comprime(orig, dest, info):
        return "o ffmpeg não conseguiu converter"
    if mb(dest) > TETO_MB * 1.1 and not comprime(orig, dest, info, 0.7):
        return "o ffmpeg não conseguiu converter"
    if mb(dest) > 45:
        os.remove(dest)
        return "ficou grande demais mesmo comprimido"
    return None


def main():
    os.makedirs(SAIDA, exist_ok=True)
    os.makedirs(TMP, exist_ok=True)
    try:
        antes = json.loads(abre(SITE_URL + "lista.json", 30))
    except Exception:
        antes = {}
    vids = videos_do_portal()
    print(f"{len(vids)} vídeos no portal")
    faltam = [i for i in vids if i not in antes]
    if antes and not faltam:                             # nada novo: não precisa publicar de novo
        txt = f"## Vídeos para o WhatsApp\nNenhum vídeo novo: os {len(vids)} vídeos do portal já têm versão leve."
        print(txt)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(txt + "\n")
        sinaliza(False)
        return
    lista, novos, falhas = {}, [], []
    for i in faltam:                                     # primeiro os novos: baixa do Drive e comprime
        t, dest, orig = vids[i], os.path.join(SAIDA, i + ".mp4"), os.path.join(TMP, "orig")
        r = subprocess.run(["curl", "-sSL", "--fail", "--retry", "3", "--max-filesize", str(1500 * 1024 * 1024),
                            "-o", orig, DRIVE.format(ATALHOS.get(i, i))])
        erro = "não consegui baixar do Drive" if r.returncode else gera(orig, dest)
        if os.path.exists(orig):
            os.remove(orig)
        if erro:
            falhas.append(f"{t} ({i}): {erro}"); print("FALHOU:", t, "-", erro)
            if os.path.exists(dest):
                os.remove(dest)
            continue
        info = sonda(dest)
        lista[i] = {"t": t, "mb": round(mb(dest), 1), "s": round(info["dur"])}
        novos.append(f"{t}: {lista[i]['mb']} MB, {lista[i]['s']} s"); print("novo:", novos[-1])
    mudou = bool(novos) or (not antes and bool(lista))
    if mudou:                                            # vai publicar de novo: junta os que já estavam no ar
        for i, t in vids.items():
            if i in antes and i not in lista:
                dest = os.path.join(SAIDA, i + ".mp4")
                try:
                    open(dest, "wb").write(abre(SITE_URL + i + ".mp4", 300))
                    if sonda(dest):
                        lista[i] = antes[i]; print("ok (já publicado):", t); continue
                except Exception as e:
                    print("aviso: não consegui reaproveitar", t, e)
                if os.path.exists(dest):
                    os.remove(dest)
                falhas.append(f"{t} ({i}): não consegui reaproveitar a versão publicada; tenta de novo amanhã")
    else:
        lista = {i: antes[i] for i in vids if i in antes}
    json.dump(lista, open(os.path.join(SAIDA, "lista.json"), "w"), ensure_ascii=False, indent=1)
    open(os.path.join(SAIDA, "index.html"), "w").write(
        "<!doctype html><meta charset=utf-8><title>Vídeos HLiving</title>"
        "<p>Versões leves dos vídeos do Portal do Corretor, para enviar pelo WhatsApp.</p>")
    total = sum(v.get("mb", 0) for v in lista.values())
    resumo = [f"## Vídeos para o WhatsApp", f"{len(lista)} de {len(vids)} prontos · {total:.0f} MB no site (limite do GitHub Pages: 1000 MB)"]
    if novos:
        resumo += ["", "### Novos"] + ["- " + n for n in novos]
    if falhas:
        resumo += ["", "### Não deu certo (continuam indo como link)"] + ["- " + f for f in falhas]
    if total > 900:
        resumo += ["", "**Atenção:** o site está perto do limite de 1 GB do GitHub Pages."]
    txt = "\n".join(resumo)
    print(txt)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(txt + "\n")
    sinaliza(mudou)


def sinaliza(mudou):
    """avisa o workflow se há o que publicar"""
    if os.environ.get("GITHUB_OUTPUT"):
        open(os.environ["GITHUB_OUTPUT"], "a").write(f"mudou={'true' if mudou else 'false'}\n")
    print("publicar:", mudou)


if __name__ == "__main__":
    main()
