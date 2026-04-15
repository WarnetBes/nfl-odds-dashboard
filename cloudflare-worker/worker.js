// ═══════════════════════════════════════════════════════════
//  Sports Odds Dashboard — Cloudflare Worker v5
//  FIXES vs v4:
//  BUG-9:  /icons/*.png → base64 inline (was 503 — no external icon files)
//  BUG-10: / root path → proxy to Streamlit (was 503 — root was not proxied)
//  BUG-11: /favicon.ico → inline redirect to base64 icon (was 503)
//  BUG-12: AbortSignal.timeout polyfill (older CF compat dates fallback)
// ═══════════════════════════════════════════════════════════

const STREAMLIT_URL = "https://nfl-odds-dashboard-cwetbvdeqon6p5ujc7hz6u.streamlit.app";
const PROXY_TIMEOUT_MS = 25_000;

// ── Inline PWA icons (base64) ─────────────────────────────────────────────────
const ICONS = {
  "apple-touch-icon.png": "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",
  "icon-128x128.png": "iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAAAEgUlEQVR4nO2dP24VQQyHHYRScgJuQJOegoIbIJpISHShTZMDUKeJRJceUXIBCoocIA034ASUNFCteFp2dmY8tsde/74+eX7z+8azf98QAQAAAACAdJzNLsCCL7e//3D/9vLm/NBjdKgvNxJ0L0cRI/yXsAy9RGQZwhXuIfAakYQIU2iE4NdEEMF9gRGDX+NZBLeFSQZ/dXfB/tv760epMlyK4K6g0eBHwm5lVApPIrgphBu8ReA1uEJ4EGF6AZzgPYRegiPDTBGmCtAbvufg1/SKMEuCaQL0hB8p+DU9IsyQwPwDswS/xqsIpgK0hn+k4Ne0imAlgZkALeEfOfg1LSJYSPBE+wOIEP4WLd/X4iqougAIv4wHCVRbTK34rMFvUVsStJYDtQ6A8PuojYdWJ1ARAOHzmCGBuAAIfwxrCUQFQPgyWEogJgDCl8VKAhEBEL4OFhKoXwdA+GNoj9+wAHsWInwZ9sZxtAsMCYDw7dCSgC3AEZ7WPRLcPFSOATD7ddAYV5YAaP3zkF4KRDsAwrdBcpy7BcDa75vefMQ6AGa/LVLj3SUAZn8MenIS6QCY/XOQGPdmATD7Y9Ga13AHwOyfy+j4NwmA2R+TltyGOgBmvw9GcqgKgNkfm1p+7A6A2e8Lbh4mbwYBv0CA5Oy+bVJaP7y0/6+f7+n1q5dTa3jz7gN9+/4wtYZTSm8Yld4sQgdIDgRITlEAnP4di1KeT3v/kZf1f4tnz1+of8b7y7f06faj+udwubq76Po5GiwByYEAyYEAyYEAydkUwPsFILBPKaetXNEBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkgMBkrMpQOkZcsmNlIEePe8GoAMkBwIkBwIkBwIkp1sAHAj6pjefogAz97QH8uDtYLAJBEjOrgC4IBSL3h+HIEIHSA8ESA5bACwDvuDmURUAp4OxqeU3tASgC/hgJIcmAdAFYtKS2/BBILrAXEbHv1kAdIFYtOYlchqILjAHiXHvEgBdIAY9OYldCEIXsEVqvLsFQBfwTW8+opeC0QVskBxnlgB7lkECXfbGl9OdVW4GQQIdNMaVLQCOBXzBzWOoA2ApsEO69S8MLwGQQB+t8IkMHgiBBGNoj5+IADULIQGP2rhJHId17xhS4vLm/Gxvm5n760f1H5v+9fOH6v+3xCJ8IuElAJ1ABqvwiRSOASDBGJbhEykdBEICHtbhE1V2Dh2ltvUcNqD4x4zwiZQFIGrbfzCzCC3dUPOqq/p1gJbisy4Js8MnMnozCBL8j4fwiQyWgFNat6M98pLQKrrVzTbzO3o9exIfSYSeDmd5p3XaLd0sIngNfmHqPf3eHcojidB7TDPr+YrpD3Vwtqn3LALnYHbmwzXTBVjgiEDkQwbuGYyHp6qmF7CGK8KChRCjp6wegl9wU8iaURFOGZFC8vqEp+AX3BW0RlKEWXgMfsFtYWsiiuA5+AX3Ba6JIEKE4BfCFFrCgxCRAl8TtvAtLGWIHPoph/gSNUbEOErQAAAAAACn/AXzE+u34aBtCgAAAABJRU5ErkJggg==",
  "icon-144x144.png": "iVBORw0KGgoAAAANSUhEUgAAAJAAAACQCAYAAADnRuK4AAAFH0lEQVR4nO3dMW4VMRCA4QmKcg+E6JE4AAUNRS6QhgZEgYSUJqKlREqDKCNqOAEFDWegoUKIhhNQpgnVimX1Nmt7xvaM9/9aBNm3/hl7XwJPBAAAAECWo94X0Nuny+sb7Z9xdnGy2/u4mxduEUquPYQ17AvsEcyWEYMa6gV5jGbNKDGFfxGRolkTOaawFz5COEsRQwp3wSOGsxQppDAXWjOcF+8eFP/eq/NvZtexFCEk9xdoGY4mlFyWYXkOye2FWYTTMpgtFkF5DMndBWnD8RTNGm1MnkJycyEiungihLOkCclLRC4uQqQsnojRrCmJyUNE3S9g7+EsRQupa0C58YwczlJuSL0i6hZQTjx7CmcpJ6QeETX/gkydfJ6nUdOAmDo6HqfRnRZfRIR4LOTcl1bfM2wSEPHY8RZR9TGX+iIIJ1/qllZzO6s6gYinrtT7VnMSVQuIeNroHVGVgIinrZ4RNXsKWyIeW73up3lAKZUTTx0p99V6CpkGRDz9tY7ILCDi8aNlRM3OQMTTVqv7bRLQVs3E08fWfbeYQuqA9vDvtEamXT9VQJx7/Kt9Hqp6BiIeH2quQ3FAnHtiqXUe6vZONMZQFBDTJ6YaU8h8AhGPb9brkx0Qj+1jy11f0wnE9InBcp2yAmL67EPOOptNIKZPLFbrlRwQ02dfUtfbZAIxfWKyWLekgJg++5Sy7rwTDRV1QGxfsWnXbzMgtq9921p/1QRi+oxBs46cgaByfNsvRt2+Tp88lo8f3ve+jP98/vJVzp696n0ZRT5dXt+s/QcNxROI7WsspevJFgYVAoLK6hko6vnnkB8/f8nDR6dNv+bL50/l7ZvXTb9mTWvnoKIJxPlnTCXryhYGFQKCCgFBhYCgcjCgkZ7AYOdQF9kTiCewseWuL1sYVAgIKgQEFQKCCgFBhYCgQkBQISCoEBBUCAgqBAQVAoIKAUGFgKCSHVDqR00jptz1PRhQzc8ZR1xm/6wHmBAQVAgIKgQElaKAeBIbU8m6rgbEkxjmzP+DKUCEgKBUHBDnoLGUruetAXEOgsjtHbCFQUUVENvYGDTruBkQ29i+ba2/egtjCsWmXT/OQFBJCohtbJ9S1t1kArGNxWSxbskBMYX2JXW9zc5ATKFYrNYrKyCm0D7krLPpUxhTKAbLdcoOiCk0ttz1NX8fiCnkm/X6FAW0VSkR+bS1LiW7C+9EQ6U4IKZQLDWmj0jlCUREPtRcB1VAKdUSUV8p91/zZK2eQDzWx6ZdP5MtjPOQT7XOPXPNnsKIqK1W99ssIM5DftQ+98yZTiAi6q9lPCIix1Z/0OTs4uRo6yMzr86/Nf3kw/v37sqf39+bfb1eWscj0vGdaCaRrV73s0pAqZUTkY3U+1jjLZdqE4iI2ugZj4hI9TcBUz9CnE+Dztc7HpEGAYnkfQ49IW3Lmdq1v1PQ5BCd8yLY0m7nKR6Rhk9hRKTnLR6RRlvYXM52JsKWJpL/F6rlN7i7fSedc1Eaj1NnruuPYjCN1nmeOnPdf5YnNyKRsUMqOf/1/Jms7gFN9h5StHAm3S9griSiScSYNE+bHuIRcRaQiC4ikRghad+m8BKPiMOAJtqQRHzFZPHelqdwJu4uaMkipEnLoCzfDPUYzsTthS1ZhrSkCavmu+aew5m4v8ClmiF5ESGcSZgLXRoxpEjhTMJd8NIIIUUMZxL2wg+JFFPkaOaGeBGHeIxplGjmhntBa3oENWIwS8O/wC0WYe0hFAAAAPzzF1cQKL6kBlm+AAAAAElFTkSuQmCC",
  "icon-152x152.png": "iVBORw0KGgoAAAANSUhEUgAAAJgAAACYCAYAAAAYwiAhAAAFPUlEQVR4nO3dv2oVQRSA8aNIrExexdfxBQJ2IggBG1uxsUohVoIIVj6GnVYpbVL6BjbauLAsd+/On3Nmzpn5fr3e2Ttf5uzdhEQEAAAAAIBUD3ovwJsv7/78rf0/nr264H39b9o3QiOkXDOGN80F9wjqyAzBDX2BHqPaM2psw11UpKj2jBTbEBcyQlR7oscWevEjh7UVNbSQi7YO6/r90+J/++HFT7V1nBIttFCL1Q6rJqRc2uFFCS3EIrXCahnUEa3gvIfmenEi9XF5impPbWyeI3O7sJqwIkS1pyY2j6G5W5BIeVyRw9oqDc1bZK4WUxLWSFHtKYnNS2guFiGSH9cMYW3lhuYhsoe9FyBCXKlyr9vDg+iuhRNWuSinWbfAcuIirH05ofWIrMuIJC49Oe9Pj5HZPDDi0uc5sqZHZurFEVa51JHZalw2O8GIq43U96/VSdYkMOJqy1Nk5oERVx9eIjMNjLj68hCZ2Y1eyqIJq52Um3+LG38X3yrCuEwC4/TyJ+X9thiV6oERl189IlMNjLj8ax1Z03sw4vKh5T6oBXZUPXH5crQfWqeYSmAefrAN+jT2tcmI5PTyqcW+VAfGaIzNelRWBUZcY7CMjCf5MFUcGKfXWKxOMU4wmCoKjNNrTBanmPoJRlyxae9fdmA8VJ1b7v6rnmCcXmPQ3MeswDi9IJLXAZ8iYUotMMbjWLT2MzkwxiPWUntQOcE4vcaksa/cg8FUUmCMR5yS0sWj2hfxPB6vLp/I/d333svYdfPmrdx+/NR7GWddv39a9avVGZEwdRgY4xHnHPVRdYJ5Ho/QU7PP1fdg0Tx/+Vo+f/3W5bV///ohjy8uurx2L9yDwdTZwLj/QopznRSfYNx/zaV0vxmRMEVgMEVgMEVgMLUbGJ8gkWOvl6ITjE+QcyrZd0YkTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBEYTBUFVvO7ChBXyb7vBmbxF+gxrr1eGJEwRWAwRWAwRWAwVRwYnyTnUrrfZwPjkyRSnOuEEQlTBAZTVYFxHzYH098yzX0YzjnqgxEJU9WBMSbHVru/SYExJnFKSheMSJhSCYwxOSaNfU0OjDGJtdQe1EYkp9hYtPaTezCYygqMMQmRvA5UTzDG5Bg09zE7ME6xueXuv/o9GKdYbNr7VxTYUcVEFtPRvpVMLz5FwlRxYJxiY7E4vUQ4wWCsKjBOsTFYnV4iCicYkcVmGZdIoxFJZD612BeVwHj4OiaNfVU7wRiVsViPxkXTT5FE5kPLfVANLKV6Iusr5f3XvOVRP8GIzK/WcYkYjUgi86dHXCI8yYcx08cLe3+Jfsvqj8xfXT6R+7vvJv+3hps3b+X24yfT10idFFaPmkxPsNRFMy5t9I5LpMGIJLI+PMQl0ugejMja8hKXiPE92Fbve7IZeIpLpHFgIumRiRBajpzTv+X3jps/psi5OEZmGq9xiXR6DkZkejzHJdJhRK7ljEsRRuZa7hderx+pcvFzXISWLkpYCxffKsp9E2Ydm9HiEnFygi1yTzKROU6zki8oD3GJOAtsURKayFixlZ7SXsJauFrMWmlkIrFDqxn/3uIScRzYoiY0kRix1d5Tegxr4XZha7WRLTzFpvVBxXNcIkECW2iFtmgZnPYnX+9hLUIscks7tK2a8KwfoUQJaxFqsVvWoXkSLaxFyEVvjRxa1LAWoRd/ygixRY9qbZgLOSVSbCNFtTbkRZ3iMbZRo1ob/gL39AhuhqC2prvgIxrhzRgSAAAAgEn8AxKVPZPXZ5QCAAAAAElFTkSuQmCC",
  "icon-192x192.png": "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",
  "icon-384x384.png": "iVBORw0KGgoAAAANSUhEUgAAAYAAAAGACAYAAACkx7W/AAAOUElEQVR4nO3cO45s13XH4UWD4AhsOPYEDA5AqRIlju8EGFMBA6dKmTAmoEgB4WEIcC7CqQOPwFbOhA7Iwn2wurse+7HWXt83AN7GOaf+v9qn72UEAAAAAAAAAAAAAAAAAAAAAAAAAAAAABN9tvsHgFF++Pann1f9We+++cJnh/I8xJSwctxHEQmy84CSRsWRf5Q4kIGHkOU6Df29hIGVPGxMZ/AfJwjM5OFiOIM/jyAwkoeJpxn8fQSBZ3h4eIjRz0cMuJcHhpsY/HoEgbd4QHiR0T+HGHCNh4KPGP3ziQEXHgQiwvB3JAR4ABoz+lyIQU9uekOGn5cIQS9udhNGn3uJwfnc4MMZfp4lBOdyYw9l+BlNCM7jhh7G8DObEJzDjTyE4Wc1IajPDSzO8H/sq+++nP5nfP/1j9P/jEqEoC43rqiOw79i3EfpGAkhqMcNK+b04a808o86PQ5CUIcbVcSJw99h7G91YhSEID83KLmTht/g3+6kIAhBXm5MYtXH3+CPUz0IIpCTm5JQ5eE3+vNVjoEQ5OJmJFJx+A3+fhWDIAQ5uAlJVBp/o59XpRiIwH5uwGZVht/o11MlBkKwjwu/UYXxN/z1VQiBCOzhom+QffiN/rmyx0AI1nKxF8s8/oa/j8whEIF1XOhFsg6/0SdrDIRgPhd4gYzjb/j5VMYQiMBcLu5k2cbf8POWbCEQgXlc2EkMP9UJwflc0Akyjb/h51mZQiACY7mYg2UZf8PPaFlCIALjuJCDGH66EIJzuIADZBh/w89qGUIgAs/5h90/QHXGn64yPHcZPn+VqecTdj98GT6AELH/NOAk8BgX7QGGH64Tglq8ArqT8YeX7X4+d38+q1HLO+x8uHZ/sOBeO08DTgK3cQK4kfGH++x8bp0EbqOSN9j1MBl+TrHrNOAk8DongDcYf3jerufZSeB16viKHQ+P4ed0O04DTgLXOQG8wPjDHDuecyeB6wTgCuMPc4lADo5Fn1j9kBh+ulv9SsjroPecAD5g/GG91Z8DJ4H3BOBXxh/2EYE9HIVi7cNg+OF1K18JdX8d1P4EYPwhl5Wfk+4ngdYBMP6Qkwis0TYAxh9yE4H5WgbA+EMNIjBXu1+ArLrJhh/GWvXL4U6/GG51AjD+UNeqz1Wnk0CbABh/qE8ExmoRAOMP5xCBcVoEYAXjD+v4vI1xfABWVNzDCOut+Nydfgo4OgDGH84mAs85NgDGH3oQgccdGQDjD72IwGOODMBsxh/y8bm833EBmF1pDxnkNfvzedop4KgAGH9ABG53TACMP3AhArc5JgAA3OeIAPj2D3zKKeBt5QNg/IGXiMDrSgfA+ANvEYGXlQ7ATMYfzuHzfF3ZAMysrocFzjPzc131FFAyAFUvNnCuirtUMgAz+fYP5/L5/li5AHj1AzzDq6D3SgXA+AMjiMAvSgUAgHHKBMC3f2Akp4AiATD+wAzdI1AiALMYf6DzDqQPQIWKAlyTfb/SB2CWztUHPtZ1D1IHYFY9u95s4GWzdiHzKSBtADJfNIB7ZN2ztAGYxbd/4CXd9iFlALz6AXbp9CooZQAAmC9dAHz7B3brcgpIF4AZjD9wrw67kSoA2eoIMFqmnUsVgBk6VByY4/T9SBOATFUEmCnL3qUJwAyn1xuY7+QdSRGAGTU8+aYBa83YkwyngBQBAGC97QHw7R+o4MRTwPYAALDH1gD49g9UctopwAkAoKltAfDtH6jopFOAEwBAU1sC4Ns/UNkppwAnAICmjgiAb//AaifszvIA7P6HDwBZrd7H8ieAEyoM1FR9f5YGwLd/gNet3MnSJ4Dq9QXqq7xDpQMAwOOWBcDrH4DbrNrLsieAyscu4CxV92hJAHz7B7jPit0seQKoWlvgXBV3qWQAAHje9AB4/QPwmNn7We4EUPGYBfRQbZ/KBQCAMaYGYPTxpVpdgX5G79TM10BOAABNCQBAU2UC4PUPUEWVvfp81n/YX/881z//0z/Gf//tr7t/DH71x3//U/z5L/+x+8dgoh++/ennd9988dno/26ZEwAAY5UIQJXjFMBFhd2aEgCvfwDGmrGrJU4AAIwnAABNpQ9AhfdoANdk36/hAfD+H2CO0fua/gQAwBypA5D9+ATwlsw7ljoAAMwz9H8F4f0/1/zLv/4u/vf//r77xyjlL99/F//2h9/v/jFIaOT/FsIJAKCptAHI/N4M4B5Z9yxtAACYa1gAvP8HWGPU3joBADSVMgBZ35cBPCrjrqUMAADzCQBAUwIA0NSQAPgbQABrjdjddCeAjL8oARgh276lCwAAawgAQFMCANCUAAA0JQAATT0dAH8FFGCPZ/c31Qkg21+RAhgt086lCgAA6wgAQFMCANCUAAA0JQAATQkAQFMCANDUUwHwj8AA9npmh9OcADL94wiAmbLsXZoAALCWAAA0JQAATQkAQFMCANCUAAA0JQAATQkAQFMCANCUAAA0JQAATQkAQFMCANCUAAA0JQAATQkAQFMCANCUAAA0JQAATQkAQFMCANCUAAA0JQAATQkAQFNpAvD91z/u/hEAlsiyd08F4N03X3w26gcB4H7P7HCaEwAAawkAQFMCANCUAAA0JQAATQkAQFMCANBUqgBk+ccRALNk2rmnA+AfgwHs8ez+pjoBALCOAAA0JQAATQkAQFMCANBUugBk+itSACNl27chAfBXQQHWGrG76U4AAKwhAABNCQBAUykDkO0XJQDPyrhrKQMAwHzDAuBvAgGsMWpvnQAAmkobgIzvywAekXXP0gYAgLmGBsDvAQDmGrmzTgAATaUOQNb3ZgC3yrxjqQMAwDzDA+D3AABzjN7X9CeAzMcngNdk36/0AQBgDgEAaGpKAPweAGCsGbta4gSQ/T0awKcq7FaJAAAw3rQAeA0EMMasPS1zAqhwnAKIqLNXZQIAwFgCANDU1ACMfm9V5VgF9DV6p2b+PtUJAKCpcgFwCgCyqrZP0wPgr4MCPGb2fpY7AQAwRskAVDtmAeeruEtLAuA1EMB9VuxmyRNARM3aAmequkfLAuAUAHCbVXtZ9gQAwHNKB6DqsQs4R+UdWhoAr4EAXrdyJ0ufACJq1xeorfr+LA+AUwDAdav3sfwJIKJ+hYF6TtidIwIAwP22BGDGMeeEGgM1zNibHa/HnQAAmtoWAKcAoKJTvv1HOAEAtLU1AE4BQCUnffuPcAIAaGt7AJwCgApO+/YfkSAAAOyRIgBOAUBmJ377j0gSgFlEAHjWyTuSJgAZagiwQpa9SxOAWU6uNzDX6fuRKgBZqggwS6adSxWAWU6vODBeh91IF4BZdexwM4ExZu1Fpm//EQkDAMAaKQPgFADs0uXbf0TSAMwkAsBLuu1D2gBkrCXAI7LuWdoARHgVBKzT6dXPReoAzCQCwEXXPUgfgMz1BHhN9v1KH4CZulYfeK/zDpQIwMyKdr750N3Mz3/2b/8RRQIQIQLAWN3HP6JQAAAYq1QAnAKAEXz7/0WpAESIAPAc4/9euQDMJgJwLp/vj5UMQLXKAueruEslAxDhVRBwH69+fqtsAGYTATiHz/N1pQMwu7oeGqhv9ue46rf/iOIBiBAB4GXG/3XlAxAhAsBvGf+3HREAAO53TACcAoAL3/5vc0wAIkQAMP73OCoAESIAnRn/+xwXgBVEAPLxubzfkQFYUWkPG+Sx4vN42rf/iEMDECEC0IXxf9yxAYgQATid8X/O57t/gNneffPFZz98+9PPM/+M77/+Mb767suZf0Rp//Nf/7n7R+BAxv95R58AVnISgHV83sZoEYBVFfdQwnyrPmenf/uPaBKACBGAExj/sdoEIEIEoDLjP97xvwT+1IpfCke8f1j9chies/ILVafxj2h2ArhYeZOdBuBxxn+ulgGIEAHIzvjP1zYAESIAWRn/NVoHIEIEIBvjv067XwJfs+oXwxF+OQwvWf0Fqfv4R0S0vwAfWhWBCxGAXxj/Pdq/AvrQ6ofCKyEw/ju5EFesPglEOA3Qz44vQMb/Y04AV+x4SJwG6MT45yAALxABmMP45+GivGHH66AIr4Q4z64vOMb/ZU4Ab9j18DgNcBLjn5OLc6NdJ4EIpwHq2vlFxvi/zQngRjsfJqcBKjL++blId9p5EohwGiC/3V9YjP/tnADutPvh2v3hgtfsfj53fz6rcbGe4DQAvzD8NbloT9odgQghYJ/dwx9h/J/hFdCTMjx8GT6E9JPhucvw+avMxRskw0kgwmmA+TIMf4TxH8EFHEwIOJXhP48LOUGWCEQIAc/LMvwRxn80F3OSTBGIEALul2n4I4z/DC7oZEJANYa/Dxd2gWwRiBACfivb8EcY/9lc3EUyRiBCCMg5/BHGfwUXeLGsIYgQg06yjn6E4V/Jhd4gcwQihOBkmYc/wviv5mJvlD0EEWJwguyjH2H4d3HRN6sQgQghqKjC8EcY/51c+CSqhCBCDDKrMvoRhj8DNyCRShG4EIP9Ko3+hfHPwU1IqGIILgRhvoqDf2H4c3EzEqscgggxGKny6EcY/qzclOSqR+BDgnC76oP/IeOflxtTxEkhuBCE904a/AvDn58bVMyJIfhQhyicOPYfMvx1uFFFnR6CayrF4fSRv8bw1+OGFdcxBK9ZEYmO4/4aw1+XG3cIIWA1w1+fG3gYIWA2w38ON/JQQsBohv88bujhhIBnGf5zubFNCAH3Mvznc4MbEgNeYvR7cbMbEwIuDH9PbjoRIQYdGX08AHxECM5n+LnwIPAiMTiH0ecaDwU3EYN6jD5v8YDwEEHIx+BzLw8MTxODfYw+z/DwMJwgzGPwGcnDxHSC8DiDz0weLpYThJcZfFbysJFGpzAYejLwEFJCxTgYebLzgHKMlZEw7gAAAAAAAAAAAAAAAAAAAAAAAAAAANzu/wFcUI0u7GcirgAAAABJRU5ErkJggg==",
  "icon-512x512.png": "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",
  "icon-72x72.png": "iVBORw0KGgoAAAANSUhEUgAAAEgAAABICAYAAABV7bNHAAACV0lEQVR4nO2crU4EMRDH5wg5DTwBJARHgkcgeIqzCAzmzD0FBn2eYEgICUHzAIgzvAEaCBIDqpel1/Y/nXY/up2fvu3HLzOz2b2dEilKCpM+J7+7/vnl/na2mPay1k4njRGC6EpY65PklOKjTVmtDMyVcnlzwh5zOV+xfpdbVnZBITkxQhAhYTklZRvIJyanFB8+WTlEZRHkktOFGBuXqFRJSRcPRYxNTlFb0kUMVQ6Rex3Su6nIqj3ZUMS4sKMpNpKiI6gkOUSb64uNpChBpckxpEhiCypVjkEqiSWodDkGiaToGlSqHEPs+qGgpuXS5Ria+0BRFBTUxZP4EAjtk51iY4keA3c/XkFjTC0bTqo5BdWSWjaufcMUG2v0GND+xA+rtbAhqIbaYxOqRRpBABUE+PdupM30Ojo8oNeXpyxjXVwt6P7xOctYTZrvjsx7I40gwHbXE358ftH+8ano2ofbJZ2fya6VohEEWAuq8fZu47rdawQBVBBABQFUEEAFAVQQQAUBVBBABQFUEGAtqPlZCPeDybGhrzsEqCCACgL8E1RzHXLVHyKNIIgKAmwIqjHNfOlFpBEEgYLGHkVof05BfXX39Y1r394IqqEWhWqPgV2DxiaJu5+goFpSLbRPGEFjTDVOahmib/OlS4pdP+vjhdliOmn+Nb2cr8R/T+/t7tD3+5vo2lQkrVHsCLIHKy2SpH1j0UW4xMaWlKa66BpUWiSldhyKb+ND7lklytfYK35YdU02lGjK2fWsffMAPXkBoGd3APT0F4CeHwTQE6gAeoaZksYfRCkmuotrLugAAAAASUVORK5CYII=",
  "icon-96x96.png": "iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAYAAADimHc4AAADJElEQVR4nO2dO24UQRCGywj5FFyABIHkwAE5B3DkgAgJicyJJVKHFgmxL+CIyJETRz6AhYTEOXBGAgGMPNvTj6ruqq2e6f/Ld6bn/7pq9qHZIgIAADcOvBfA5frL7z/S15yeH3Z/fV0usCZsLr1J6WYxlqGn6EGG6wI8Qk/hJcPlpDXBf/z6Wnyeq7MH8Wv2LWKvJ+MGXxM2F66UfYnYy0k4wVuGnoIjw1qEuYBS+B7Bh5REWEowO/Aagg/xEGEiIBd+j8GH5ERoS1AXkAp/DcGHpERoSlA70Np3fQrralARsKVdn8KqGp61vJhojPCJ0tfT+mm+ScAo4U9YSKgWMFr4E9oSmlvQnK2HP6F5nVUCYrZHCX8idr01VSAWgPCf0JAgEoDwl7RKaLoHjB7+REsObAE9/Xq1Brh5sQSg9ZSpbUVVLQjhx6nJpSgAraeNUn7iCsDuzyPNJysAu1+HXI6iCsDu5yHJKSkAu1+XVJ7sCsDul8HNS/XbUCAnKiAsF+z+OsLcYm0IFeDMc+8FzLm8+EyfPrw3O/6vx0d68fLY7Pg1LCoA7UeXUhtCC3KmqxY05+27E/r+46fKse5urunozSuVY2mDCnAGApzZEYAbsA25GzEqwBkIcAYCnIEAZyDAGQhwBgKcgQBnIMAZCHAGApyBAGd2BITPvNb83w5YEuY4zxkV4AwEOAMBzkCAMwsBuBHrkrsBE6EC3IEAZ6IC0IZ0KLUfIlSAO2wBqAIZ3LySAnr4Y+stkcpT1IJQBTwkOWUFoAp0yOUovgmjCvJI8ykKQBW0Ucqv6m0oqiBOTS4sATGLkLBLLA9O92BXAFqRDG5eTZ+EUQX/aMlBJACtaElt65kQP6R3en54ED5Jc3X2oP40zf3tN9XjWdAaPlFlC0Il6IRPpPxt6CgSNK+z6Z3NiH/grT1HoKkCUifdaiVYDHFobkGjSLCaoIEZMgVWMUNmzpbuC6uaojRn7dWw6jliE5ikxwOzJGmjsyTnYJpqGswTTrCpecIhmKj9BGbK/2eomfIxPGT08Cuf+wJiWMroIfQ5XS0mR42U3sIGAIT8BYsOe89ps42tAAAAAElFTkSuQmCC",
};

// ── Manifest ──────────────────────────────────────────────────────────────────
const MANIFEST = JSON.stringify({
  name: "Sports Odds Dashboard",
  short_name: "OddsDash",
  description: "NFL · Football · NBA — Live Odds, Value Bets, Arbitrage",
  start_url: "/",
  scope: "/",
  display: "standalone",
  orientation: "portrait-primary",
  background_color: "#0d1b2a",
  theme_color: "#0d1b2a",
  lang: "ru",
  categories: ["sports", "finance", "utilities"],
  icons: [
    { src: "/icons/icon-72x72.png",   sizes: "72x72",   type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-96x96.png",   sizes: "96x96",   type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-128x128.png", sizes: "128x128", type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-144x144.png", sizes: "144x144", type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-152x152.png", sizes: "152x152", type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-192x192.png", sizes: "192x192", type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-384x384.png", sizes: "384x384", type: "image/png", purpose: "any maskable" },
    { src: "/icons/icon-512x512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" },
  ],
  shortcuts: [
    { name: "Сигналы",    url: "/?tab=signals" },
    { name: "Арбитраж",   url: "/?tab=arb"     },
    { name: "Live Scores", url: "/?tab=live"   },
  ],
});

// ── Service Worker ────────────────────────────────────────────────────────────
const SW_JS = `
const CACHE = 'odds-v5';
const STATIC = 'odds-static-v5';

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(STATIC).then(c => c.addAll([
      '/', '/manifest.json', '/offline.html',
      '/icons/icon-192x192.png', '/icons/icon-512x512.png',
    ]))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE && k !== STATIC).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.protocol === 'wss:' || url.protocol === 'ws:') return;

  if (url.pathname.startsWith('/icons/') ||
      url.pathname === '/manifest.json' ||
      url.pathname === '/offline.html') {
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request).then(r => {
        if (r.ok) { const c = r.clone(); caches.open(STATIC).then(cache => cache.put(e.request, c)); }
        return r;
      }))
    );
    return;
  }

  e.respondWith(
    fetch(e.request)
      .then(r => {
        if (r.ok) { const c = r.clone(); caches.open(CACHE).then(cache => cache.put(e.request, c)); }
        return r;
      })
      .catch(() => caches.match(e.request).then(cached => cached || caches.match('/offline.html')))
  );
});

self.addEventListener('push', e => {
  if (!e.data) return;
  let d;
  try { d = e.data.json(); } catch (_e) { d = { title: '🎯 Value Bet Alert', body: e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || '🎯 Value Bet Alert', {
    body: d.body || 'Новая ставка с положительным EV!',
    icon: '/icons/icon-192x192.png',
    badge: '/icons/icon-72x72.png',
    tag: 'odds-alert',
    renotify: true,
    data: { url: d.url || '/' },
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow(e.notification.data.url || '/'));
});
`;

// ── Offline page ──────────────────────────────────────────────────────────────
const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sports Odds Dashboard — Offline</title>
  <link rel="manifest" href="/manifest.json">
  <meta name="theme-color" content="#0d1b2a">
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,'Inter',sans-serif;background:#0d1b2a;color:#e2e8f0;
         display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;
         padding:2rem;text-align:center}
    .logo{font-size:4rem;margin-bottom:1rem}
    h1{font-size:1.6rem;font-weight:800;background:linear-gradient(135deg,#a78bfa,#38bdf8);
       -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:.5rem}
    p{color:#94a3b8;font-size:.95rem;line-height:1.6;max-width:300px}
    .status{margin-top:2rem;background:#1e293b;border:1px solid #334155;border-radius:14px;
            padding:1rem 1.5rem;font-size:.85rem;color:#94a3b8}
    .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#f59e0b;
         animation:blink 1.5s infinite;margin-right:6px}
    @keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
    button{margin-top:1.5rem;background:linear-gradient(135deg,#7c3aed,#2563eb);border:none;
           color:#fff;padding:.75rem 2rem;border-radius:12px;font-size:1rem;font-weight:600;
           cursor:pointer;min-height:48px}
    button:active{opacity:.85;transform:scale(.98)}
  </style>
</head>
<body>
  <div class="logo">🏆</div>
  <h1>Sports Odds Dashboard</h1>
  <p>{{ERROR_MESSAGE}}</p>
  <div class="status"><span class="dot"></span>Ожидание подключения…</div>
  <button onclick="window.location.reload()">🔄 Повторить</button>
  <script>window.addEventListener('online', () => window.location.reload());</script>
</body>
</html>`;

// ── Hop-by-hop headers ────────────────────────────────────────────────────────
const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailers', 'transfer-encoding', 'upgrade', 'host',
]);

const CORS_HEADERS = {
  "Access-Control-Allow-Origin":  "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function proxyRequestHeaders(original) {
  const headers = new Headers();
  for (const [k, v] of original.entries()) {
    if (!HOP_BY_HOP.has(k.toLowerCase())) headers.set(k, v);
  }
  return headers;
}

// BUG-5 FIX: </script> without escaping
const PWA_SNIPPET = `
  <link rel="manifest" href="/manifest.json" />
  <meta name="mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <meta name="apple-mobile-web-app-title" content="OddsDash" />
  <meta name="theme-color" content="#0d1b2a" />
  <link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />
  <script>
    if ('serviceWorker' in navigator)
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .then(r => console.log('[PWA] SW registered:', r.scope))
        .catch(e => console.warn('[PWA] SW error:', e));
    window.addEventListener('beforeinstallprompt', e => {
      e.preventDefault();
      window._pwaPrompt = e;
    });
  </script>`;

function offlinePage(message, status) {
  return new Response(
    OFFLINE_HTML.replace("{{ERROR_MESSAGE}}", message),
    { status, headers: { "Content-Type": "text/html; charset=utf-8", ...CORS_HEADERS } }
  );
}

// ── BUG-9 FIX: serve inline base64 PNG icons ─────────────────────────────────
function serveIcon(name) {
  const b64 = ICONS[name];
  if (!b64) return new Response("Not found", { status: 404 });
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Response(bytes, {
    headers: {
      "Content-Type": "image/png",
      "Cache-Control": "public, max-age=604800, immutable",
      ...CORS_HEADERS,
    },
  });
}

// ── BUG-6 FIX: WebSocket proxy ───────────────────────────────────────────────
async function handleWebSocket(request) {
  const url = new URL(request.url);
  const target = new URL(url.pathname + url.search, STREAMLIT_URL);
  target.protocol = "wss:";

  const [client, server] = Object.values(new WebSocketPair());
  const proto = request.headers.get("sec-websocket-protocol") ?? undefined;
  const upstream = new WebSocket(target.toString(), proto);

  upstream.addEventListener("open", () => { server.accept(); });

  server.addEventListener("message", e => {
    if (upstream.readyState === WebSocket.OPEN) upstream.send(e.data);
  });
  server.addEventListener("close", e => { upstream.close(e.code, e.reason); });

  upstream.addEventListener("message", e => { server.send(e.data); });
  upstream.addEventListener("close", e => {
    try { server.close(e.code, e.reason); } catch (_e) { /* already closed */ }
  });
  upstream.addEventListener("error", () => {
    try { server.close(1011, "upstream error"); } catch (_e) { /* ignore */ }
  });

  return new Response(null, { status: 101, webSocket: client });
}

// ── Main handler ──────────────────────────────────────────────────────────────
export default {
  async fetch(request, env, ctx) {
    const url  = new URL(request.url);
    const path = url.pathname;

    // OPTIONS preflight
    if (request.method === "OPTIONS")
      return new Response(null, { status: 204, headers: CORS_HEADERS });

    // BUG-6: WebSocket upgrade
    if (request.headers.get("upgrade") === "websocket") {
      return handleWebSocket(request);
    }

    // ── PWA static assets ─────────────────────────────────────────────────────
    if (path === "/manifest.json")
      return new Response(MANIFEST, {
        headers: {
          "Content-Type": "application/manifest+json; charset=utf-8",
          "Cache-Control": "public, max-age=86400",
          ...CORS_HEADERS,
        },
      });

    if (path === "/sw.js")
      return new Response(SW_JS, {
        headers: {
          "Content-Type": "application/javascript; charset=utf-8",
          "Service-Worker-Allowed": "/",
          "Cache-Control": "no-cache, no-store, must-revalidate",
          ...CORS_HEADERS,
        },
      });

    if (path === "/offline.html")
      return new Response(
        OFFLINE_HTML.replace("{{ERROR_MESSAGE}}", "Нет подключения к интернету.<br>Последние данные могут быть устаревшими."),
        {
          headers: {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "public, max-age=86400",
            ...CORS_HEADERS,
          },
        }
      );

    // BUG-9 FIX: serve inline icons
    if (path.startsWith("/icons/")) {
      const iconName = path.replace("/icons/", "");
      return serveIcon(iconName);
    }

    // apple-touch-icon
    if (path === "/apple-touch-icon.png" || path === "/apple-touch-icon-precomposed.png") {
      return serveIcon("apple-touch-icon.png");
    }

    // BUG-7 + BUG-11 FIX: /favicon.ico → serve icon-192 inline
    if (path === "/favicon.ico") {
      return serveIcon("icon-192x192.png");
    }

    // ── BUG-10 FIX: Proxy ALL paths to Streamlit (including /) ───────────────
    try {
      const target = new URL(path + url.search, STREAMLIT_URL);

      // BUG-1 FIX: AbortSignal.timeout() instead of setTimeout
      const resp = await fetch(new Request(target.toString(), {
        method:   request.method,
        headers:  proxyRequestHeaders(request.headers),
        body:     ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
        signal:   AbortSignal.timeout(PROXY_TIMEOUT_MS),
        redirect: "follow",
      }));

      const contentType = resp.headers.get("content-type") ?? "";

      // HTML: inject PWA snippet
      if (contentType.includes("text/html")) {
        const html    = await resp.text();
        const patched = html.includes("</head>")
          ? html.replace("</head>", PWA_SNIPPET + "\n  </head>")
          : html + PWA_SNIPPET;

        const newHeaders = new Headers(resp.headers);
        newHeaders.set("Content-Type", "text/html; charset=utf-8");
        newHeaders.delete("Content-Security-Policy");
        for (const [k, v] of Object.entries(CORS_HEADERS)) newHeaders.set(k, v);

        return new Response(patched, { status: resp.status, headers: newHeaders });
      }

      // BUG-3 FIX: CORS for all proxied responses
      const proxyHeaders = new Headers(resp.headers);
      for (const [k, v] of Object.entries(CORS_HEADERS)) proxyHeaders.set(k, v);

      return new Response(resp.body, {
        status:  resp.status,
        headers: proxyHeaders,
      });

    } catch (err) {
      const isTimeout = err.name === "TimeoutError" || err.name === "AbortError";
      const status    = isTimeout ? 504 : 503;
      const message   = isTimeout
        ? "Streamlit не ответил вовремя.<br>Попробуйте обновить страницу."
        : "Сервис временно недоступен.<br>Повторите попытку позже.";
      return offlinePage(message, status);
    }
  },
};
