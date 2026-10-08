def sat_i8(value):
    return max(-128, min(127, value))


def relu_quant(acc, shift=4):
    value = max(0, acc)
    value = (value + (1 << (shift - 1))) >> shift
    return sat_i8(value)


def inference(features, w1, b1, w2, b2, threshold):
    hidden = []
    mac_effective = 0

    for out_idx in range(16):
        acc = b1[out_idx]
        for in_idx in range(16):
            weight = w1[out_idx][in_idx]
            if weight != 0:
                acc += int(features[in_idx]) * int(weight)
                mac_effective += 1
        hidden.append(relu_quant(acc))

    score = b2
    for idx in range(16):
        score += int(hidden[idx]) * int(w2[idx])
        mac_effective += 1

    alarm = int(score >= threshold)
    return score, alarm, mac_effective


if __name__ == "__main__":
    features = [4, -2, 7, 0, 1, 3, -1, 5, 2, 0, 1, -3, 2, 4, 0, 1]

    w1 = [
        [0 if (row * 16 + col) % 3 == 0 else ((row + col) % 7 - 3)
         for col in range(16)]
        for row in range(16)
    ]
    b1 = [0] * 16
    w2 = [1, -1, 2, 0, 1, -2, 1, 0, 1, -1, 2, 1, 0, 1, -1, 1]
    b2 = 0
    threshold = 12

    score, alarm, mac_count = inference(
        features, w1, b1, w2, b2, threshold
    )

    print(f"score       : {score}")
    print(f"alarm       : {alarm}")
    print(f"MAC efektif : {mac_count}")
    print("MAC dense   : 272")
