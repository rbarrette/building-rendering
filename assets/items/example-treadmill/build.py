"""Procedural 3D asset for matrix-tf50 (Matrix TF50 Folding Treadmill).

Item-local frame (inches): origin = footprint centre on the floor (z=0), +Z up,
FRONT (motor hood / console end) faces -Y (south) at rot 0,
BACK (rear of running deck where the runner steps on) faces +Y (north).
Bounding box: w = 34.0 (X: -17.0..+17.0), d = 79.0 (Y: -39.5..+39.5), h = 62.0 (Z: 0.0..62.0).
"""


def build(ctx):
    m_frame = ctx.mat("tf50_frame", ctx.hexrgba("#222428"))
    m_trim = ctx.mat("tf50_trim", ctx.hexrgba("#626870"))
    m_belt = ctx.mat("tf50_belt", ctx.hexrgba("#17181A"))
    m_screen = ctx.mat("tf50_screen", ctx.hexrgba("#111318"))
    m_red = ctx.mat("tf50_red", ctx.hexrgba("#C8102E"))

    frames, trims, belts, screens, reds = [], [], [], [], []
    folded = getattr(ctx, "state", "open") == "folded"

    if folded:
        # Folded footprint: w = 34.0 (X: -17..+17), d = 44.0 (Y: -22..+22), h = 72.0 (Z: 0..72)
        for sx in (-1, 1):
            belts.append(ctx.box(sx * 15.2, -19.0, 0.0, 2.8, 3.6, 1.4))
            belts.append(ctx.box(sx * 15.2, 16.0, 0.0, 2.8, 3.6, 1.4))
            frames.append(ctx.box(sx * 14.8, -1.5, 1.2, 2.4, 38.0, 2.0))
            frames.append(ctx.box(sx * 15.6, -10.5, 1.8, 2.8, 6.4, 6.8))
        frames.append(ctx.box(0.0, -19.0, 1.2, 28.0, 2.4, 2.0))
        frames.append(ctx.box(0.0, 16.0, 1.2, 28.0, 2.4, 2.0))
        # Motor hood at -Y (-22..-5)
        frames.append(ctx.box(0.0, -20.0, 2.6, 30.8, 4.0, 8.2))
        frames.append(ctx.box(0.0, -12.7, 2.6, 31.6, 14.8, 10.4))
        frames.append(ctx.box(0.0, -12.3, 13.0, 27.6, 11.6, 1.4))
        # Uprights & handrails
        for sx in (-1, 1):
            frames.append(ctx.box(sx * 15.2, -9.7, 8.5, 2.8, 4.4, 14.5))
            frames.append(ctx.box(sx * 15.2, -7.7, 22.5, 2.8, 4.2, 14.5))
            frames.append(ctx.box(sx * 15.2, -5.7, 36.5, 2.8, 4.0, 15.0))
            trims.append(ctx.box(sx * 16.65, -7.7, 10.5, 0.3, 2.2, 37.5))
            belts.append(ctx.box(sx * 15.2, 3.5, 46.2, 2.2, 16.0, 2.2))
        # Console (z = 50.2..62.0)
        frames.append(ctx.box(0.0, -4.7, 50.2, 34.0, 8.2, 3.4))
        frames.append(ctx.box(0.0, -5.9, 53.6, 30.0, 5.8, 4.4))
        frames.append(ctx.box(0.0, -7.0, 57.6, 25.6, 4.4, 4.4))
        screens.append(ctx.box(0.0, -4.3, 56.2, 23.6, 0.9, 5.4))
        reds.append(ctx.box(0.0, -1.0, 48.2, 2.6, 2.0, 1.4))
        # Hydraulic shock & tilted upright running deck reaching z = 72.0, y = +22.0
        trims.append(ctx.box(2.5, 4.0, 4.0, 2.0, 4.0, 38.0))
        for sx in (-1, 1):
            frames.append(ctx.box(sx * 13.8, 12.5, 10.0, 4.2, 6.2, 62.0))
            trims.append(ctx.box(sx * 13.7, 9.5, 11.0, 3.8, 1.0, 60.0))
        frames.append(ctx.box(0.0, 14.0, 10.0, 23.6, 4.6, 61.5))
        belts.append(ctx.box(0.0, 11.2, 10.5, 22.8, 0.8, 60.5))
        trims.append(ctx.box(0.0, 19.0, 26.0, 22.0, 6.0, 2.0))  # rear support kickstand / bumper at y=+22
        return [
            ctx.part("frame", frames, m_frame),
            ctx.part("trim", trims, m_trim),
            ctx.part("belt_grips_feet", belts, m_belt),
            ctx.part("console_screen", screens, m_screen),
            ctx.part("safety_red", reds, m_red),
        ]

    # 1. Base Stabilizer Frame, Transport Wheels & Folding Cylinder (z = 0..4)
    # Front base feet (z0 = 0.0) & base rails under motor/uprights
    for sx in (-1, 1):
        belts.append(ctx.box(sx * 15.2, -36.5, 0.0, 2.8, 3.6, 1.4))
        frames.append(ctx.box(sx * 14.8, -23.0, 1.2, 2.4, 29.0, 2.0))
        # Upright base pivot housing reaching x = ±17.0 (w = 34.0)
        frames.append(ctx.box(sx * 15.6, -28.0, 1.8, 2.8, 6.4, 6.8))
    frames.append(ctx.box(0.0, -36.5, 1.2, 28.0, 2.4, 2.0))
    # Hydraulic folding shock tube under deck
    trims.append(ctx.box(2.5, -13.0, 2.0, 1.8, 17.0, 2.8))

    # Rear deck rubber floor feet (z0 = 0.0)
    for sx in (-1, 1):
        belts.append(ctx.box(sx * 13.8, 35.5, 0.0, 2.6, 4.4, 2.4))

    # 2. Running Deck & 20x60 Running Belt (y = -24..+39.5, z = 2.4..8.6)
    for sx in (-1, 1):
        # Structural steel deck side rails
        frames.append(ctx.box(sx * 14.0, 7.0, 2.4, 4.2, 62.0, 5.2))
        # Non-slip side foot rails with metallic trim accent
        trims.append(ctx.box(sx * 13.9, 7.0, 7.6, 4.0, 61.5, 0.9))
        belts.append(ctx.box(sx * 13.8, 7.0, 8.5, 3.2, 58.0, 0.2))
        # Rear roller end-cap housings reaching y = +39.5 (37.5 + 4.0/2 = 39.5)
        frames.append(ctx.box(sx * 13.8, 37.5, 2.4, 4.4, 4.0, 5.8))
        reds.append(ctx.box(sx * 13.8, 39.3, 4.6, 1.8, 0.4, 0.8))  # rear safety reflector/marker

    # Phenolic deck board, rear roller bar & black running belt surface (top at z = 8.2)
    frames.append(ctx.box(0.0, 7.0, 3.4, 23.6, 61.0, 4.2))
    trims.append(ctx.box(0.0, 37.2, 3.6, 23.2, 3.6, 4.0))
    belts.append(ctx.box(0.0, 7.2, 7.6, 22.8, 61.5, 0.6))

    # 3. Front Motor Hood (y = -39.5..-22.5, z = 2.6..14.4)
    # Front nose bumper reaching y = -39.5 (-37.5 - 4.0/2 = -39.5)
    frames.append(ctx.box(0.0, -37.5, 2.6, 30.8, 4.0, 8.2))
    # Main sculpted motor cover & upper louvered cowl
    frames.append(ctx.box(0.0, -30.2, 2.6, 31.6, 14.8, 10.4))
    frames.append(ctx.box(0.0, -29.8, 13.0, 27.6, 11.6, 1.4))
    trims.append(ctx.box(0.0, -35.8, 10.6, 28.4, 2.2, 0.8))

    # 4. Left & Right Console Uprights & Side Handrails (z = 8.5..51.5)
    for sx in (-1, 1):
        # Segmented upright masts leaning slightly rearward from motor base to console
        frames.append(ctx.box(sx * 15.2, -27.2, 8.5, 2.8, 4.4, 14.5))
        frames.append(ctx.box(sx * 15.2, -25.2, 22.5, 2.8, 4.2, 14.5))
        frames.append(ctx.box(sx * 15.2, -23.2, 36.5, 2.8, 4.0, 15.0))
        # Metallic silver upright shroud accents
        trims.append(ctx.box(sx * 16.65, -25.2, 10.5, 0.3, 2.2, 37.5))

        # Side handrails extending back toward runner (+Y) with closed loop return
        belts.append(ctx.box(sx * 15.2, -13.0, 46.2, 2.2, 18.0, 2.2))
        belts.append(ctx.box(sx * 15.2, -4.8, 40.5, 2.0, 2.2, 6.0))
        frames.append(ctx.box(sx * 15.2, -14.2, 39.5, 2.0, 19.0, 2.0))

    # 5. Pulse Grips, Safety Key Dock & Wide Touchscreen Console (w = 34.0, top at z = 62.0)
    # Lower handlebar & heart-rate pulse grips facing the runner (+Y)
    frames.append(ctx.box(0.0, -18.8, 47.2, 29.2, 2.6, 2.2))
    for sx in (-1, 1):
        belts.append(ctx.box(sx * 6.5, -15.8, 47.4, 4.2, 3.8, 1.8))
        trims.append(ctx.box(sx * 6.5, -15.2, 47.6, 2.4, 2.2, 1.6))
    # Central emergency stop / safety key pod
    frames.append(ctx.box(0.0, -16.2, 47.6, 4.4, 3.0, 1.8))
    reds.append(ctx.box(0.0, -15.8, 48.2, 2.6, 2.0, 1.4))

    # Console lower accessory wing / bottle holders spanning full width w = 34.0 (x = -17.0..+17.0)
    frames.append(ctx.box(0.0, -22.2, 50.2, 34.0, 8.2, 3.4))
    trims.append(ctx.box(0.0, -19.0, 52.8, 31.2, 3.2, 1.8))

    # Upper angled display housing reaching z = 62.0 (57.6 + 4.4 = 62.0)
    frames.append(ctx.box(0.0, -23.4, 53.6, 30.0, 5.8, 4.4))
    frames.append(ctx.box(0.0, -24.5, 57.6, 25.6, 4.4, 4.4))
    trims.append(ctx.box(0.0, -23.0, 55.8, 24.8, 2.0, 5.8))

    # Dark glossy touchscreen display glass & control bar facing runner (+Y side of console)
    screens.append(ctx.box(0.0, -18.8, 52.6, 27.6, 0.8, 3.6))
    screens.append(ctx.box(0.0, -21.8, 56.2, 23.6, 0.9, 5.4))

    return [
        ctx.part("frame", frames, m_frame),
        ctx.part("trim", trims, m_trim),
        ctx.part("belt_grips_feet", belts, m_belt),
        ctx.part("console_screen", screens, m_screen),
        ctx.part("safety_red", reds, m_red),
    ]
