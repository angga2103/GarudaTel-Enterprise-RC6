def hitung_crc16(data: str) -> str:
    crc = 0xFFFF
    for char in data:
        crc ^= ord(char) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"

def buat_qris_dinamis(nominal: int) -> str:
    # QRIS Statis Asli Ansor Store
    statis = "00020101021126610016ID.CO.SHOPEE.WWW01189360091800229514200208229514200303UMI51440014ID.CO.QRIS.WWW0215ID10265077429340303UMI5204481253033605802ID5911Ansor Store6006KEDIRI61056429362070703A01630486BE"
    
    # 1. Ubah kode awalan dari Statis (11) ke Dinamis (12)
    payload = statis.replace("010211", "010212")
    
    # 2. Potong gembok CRC lama (4 digit terakhir)
    payload = payload[:-4]
    
    # 3. Cari titik belah sebelum tag 58 (Kode Negara ID)
    titik_belah = payload.find("5802ID")
    if titik_belah == -1:
        return statis
        
    # 4. Format nominal (contoh: 100584)
    nominal_str = str(int(nominal))
    panjang_nominal = f"{len(nominal_str):02d}"
    tag_54 = f"54{panjang_nominal}{nominal_str}"
    
    # 5. Gabungkan kembali
    payload_baru = payload[:titik_belah] + tag_54 + payload[titik_belah:]
    
    # 6. Pasang gembok CRC baru
    return payload_baru + hitung_crc16(payload_baru)
