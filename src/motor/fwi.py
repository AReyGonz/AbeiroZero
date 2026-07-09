"""
src/motor/fwi.py
Canadian Forest Fire Weather Index (FWI) System — Van Wagner & Pickett (1985).
Reference: Van Wagner, C.E. 1987. Development and Structure of the Canadian
Forest Fire Weather Index System. Canadian Forestry Service, Forestry
Technical Report 35.
"""
import math

# Day-length adjustment factors by month (mid-latitude, Van Wagner 1987, Table)
DMC_DAYLENGTH = [6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0]
DC_DAYLENGTH  = [-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6]

class FWI:
    def __init__(self, temp, rh, wind, rain, ffmc0, dmc0, dc0, month):
        rh = min(rh, 100.0)
        self.ffmc = self._ffmc(temp, rh, wind, rain, ffmc0)
        self.dmc  = self._dmc(temp, rh, rain, dmc0, month)
        self.dc   = self._dc(temp, rain, dc0, month)
        self.isi  = self._isi(wind, self.ffmc)
        self.bui  = self._bui(self.dmc, self.dc)
        self.fwi  = self._fwi(self.isi, self.bui)

    @staticmethod
    def _ffmc(temp, rh, wind, rain, ffmc0):
        mo = 147.2 * (101 - ffmc0) / (59.5 + ffmc0)
        if rain > 0.5:
            rf = rain - 0.5
            if mo <= 150.0:
                mo += 42.5 * rf * math.exp(-100.0 / (251 - mo)) * (1 - math.exp(-6.93 / rf))
            else:
                mo += 42.5 * rf * math.exp(-100.0 / (251 - mo)) * (1 - math.exp(-6.93 / rf)) \
                      + 0.0015 * (mo - 150.0) ** 2 * math.sqrt(rf)
            mo = min(mo, 250.0)
        ed = 0.942 * rh ** 0.679 + 11 * math.exp((rh - 100) / 10) \
             + 0.18 * (21.1 - temp) * (1 - math.exp(-0.115 * rh))
        ew = 0.618 * rh ** 0.753 + 10 * math.exp((rh - 100) / 10) \
             + 0.18 * (21.1 - temp) * (1 - math.exp(-0.115 * rh))
        if mo < ed and mo < ew:
            k1 = 0.424 * (1 - ((100 - rh) / 100) ** 1.7) \
                 + 0.0694 * math.sqrt(wind) * (1 - ((100 - rh) / 100) ** 8)
            kw = k1 * 0.581 * math.exp(0.0365 * temp)
            m = ew - (ew - mo) * 10 ** (-kw)
        elif mo > ed:
            k0 = 0.424 * (1 - (rh / 100) ** 1.7) + 0.0694 * math.sqrt(wind) * (1 - (rh / 100) ** 8)
            kd = k0 * 0.581 * math.exp(0.0365 * temp)
            m = ed + (mo - ed) * 10 ** (-kd)
        else:
            m = mo
        return 59.5 * (250 - m) / (147.2 + m)

    @staticmethod
    def _dmc(temp, rh, rain, dmc0, month):
        el = DMC_DAYLENGTH[month - 1]
        t = max(temp, -1.1)
        rk = 1.894 * (t + 1.1) * (100 - rh) * el * 1e-4
        if rain > 1.5:
            re = 0.92 * rain - 1.27
            mo = 20.0 + math.exp(5.6348 - dmc0 / 43.43)
            if dmc0 <= 33:
                b = 100.0 / (0.5 + 0.3 * dmc0)
            elif dmc0 <= 65:
                b = 14.0 - 1.3 * math.log(dmc0)
            else:
                b = 6.2 * math.log(dmc0) - 17.2
            mr = mo + 1000 * re / (48.77 + b * re)
            pr = 244.72 - 43.43 * math.log(mr - 20.0)
            pr = max(pr, 0.0)
            dmc0 = pr
        return max(dmc0 + rk, 0.0)

    @staticmethod
    def _dc(temp, rain, dc0, month):
        fl = DC_DAYLENGTH[month - 1]
        t = max(temp, -2.8)
        v = 0.36 * (t + 2.8) + fl
        v = max(v, 0.0)
        if rain > 2.8:
            rd = 0.83 * rain - 1.27
            qo = 800 * math.exp(-dc0 / 400)
            qr = qo + 3.937 * rd
            dr = 400 * math.log(800 / qr)
            dr = max(dr, 0.0)
            dc0 = dr
        return dc0 + 0.5 * v

    @staticmethod
    def _isi(wind, ffmc):
        m = 147.2 * (101 - ffmc) / (59.5 + ffmc)
        ff = 19.115 * math.exp(m * -0.1386) * (1 + m ** 5.31 / 4.93e7)
        return ff * math.exp(0.05039 * wind)

    @staticmethod
    def _bui(dmc, dc):
        if dmc == 0 and dc == 0:
            return 0.0
        if dmc <= 0.4 * dc:
            return max(0.8 * dmc * dc / (dmc + 0.4 * dc), 0.0)
        return dmc - (1 - 0.8 * dc / (dmc + 0.4 * dc)) * \
               (0.92 + (0.0114 * dmc) ** 1.7)

    @staticmethod
    def _fwi(isi, bui):
        if bui <= 80:
            fd = 0.626 * bui ** 0.809 + 2.0
        else:
            fd = 1000.0 / (25 + 108.64 * math.exp(-0.023 * bui))
        b = 0.1 * isi * fd
        if b > 1:
            return math.exp(2.72 * (0.434 * math.log(b)) ** 0.647)
        return b