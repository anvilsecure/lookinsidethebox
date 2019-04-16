def _btea(v, n, k):
    MX = lambda: ((z>>5)^(y<<2)) + ((y>>3)^(z<<4))^(sum^y) + (k[(p & 3)^e]^z)
    u32 = lambda x: x & 0xffffffff
    y = v[0]
    sum = 0
    DELTA = 0x9e3779b9
    if n > 1:
        z = v[n-1]
        q = 6 + 52 // n
        while q > 0:
            q -= 1
            sum = u32(sum + DELTA)
            e = u32(sum >> 2) & 3
            p = 0
            while p < n - 1:
                y = v[p+1]
                z = v[p] = u32(v[p] + MX())
                p += 1
            y = v[0]
            z = v[n-1] = u32(v[n-1] + MX())
        return True
    elif n < -1:
        n = -n
        q = 6 + 52 // n
        sum = u32(q * DELTA)
        while sum != 0:
            e = u32(sum >> 2) & 3
            p = n - 1
            while p > 0:
                z = v[p-1]
                y = v[p] = u32(v[p] - MX())
                p -= 1
            z = v[n-1]
            y = v[0] = u32(v[0] - MX())
            sum = u32(sum - DELTA)
        return True
    return False

def tea_decipher(v, key):
    vc = v.copy()
    btea(vc, -len(vc), key)
    return vc

def tea_encipher(v, key):
    vc = v.copy()
    btea(vc, len(vc), key)
    return vc

def btea(v, n, k):
    MX = lambda: ((z>>5)^(y<<2)) + ((y>>3)^(z<<4))^(sum^y) + (k[(p & 3)^e]^z)
    U32 = lambda x: x & 0xFFFFFFFF
    DELTA = 0x9e3779b9
    sum = 0
    y = v[0]
    if n > 1:
        z = v[n-1]
        for _ in range(0, 6 + 52//n):
            sum = U32(sum + DELTA)
            e = U32(sum >> 2) & 3
            p = 0
            while p < n - 1:
                y = v[p+1]
                z = v[p] = U32(v[p] + MX())
                p += 1
            y = v[0]
            z = v[n-1] = U32(v[n-1] + MX())
        return True
    elif n < -1:
        n = -n
        sum = U32((6 + 52//n) * DELTA)
        while sum != 0:
            e = U32(sum >> 2) & 3
            p = n - 1
            while p > 0:
                z = v[p-1]
                y = v[p] = U32(v[p] - MX())
                p -= 1
            z = v[n-1]
            y = v[0] = U32(v[0] - MX())
            sum = U32(sum - DELTA)


if __name__ == "__main__":
    v = [1,2,3,4]
    k = [5,6,7,8]
    r = tea_encipher(v, k)
    r2 = tea_decipher(r, k)

    assert(id(r2) != id(v))
    assert(v == r2)
