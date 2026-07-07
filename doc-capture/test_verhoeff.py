from verhoeff import verify_aadhaar

def test_verify_aadhaar_valid():
    # Valid Aadhaar numbers passing Verhoeff checksum
    assert verify_aadhaar("361092825621") == True
    assert verify_aadhaar("999912341234") == True

def test_verify_aadhaar_invalid():
    # Changing one digit should fail the checksum
    assert verify_aadhaar("361092825624") == False
    assert verify_aadhaar("999912341233") == False
    assert verify_aadhaar("1234") == False
    assert verify_aadhaar("abcdefghijkl") == False
