package tomes;

import net.minecraftforge.fml.common.Mod;

// Мод без кода: всё содержимое — ресурсы (книги Patchouli, рецепты, достижения).
@Mod(modid = Tomes.MODID, name = "Tomes", version = Tomes.VERSION,
     acceptedMinecraftVersions = "[1.12.2]", dependencies = "after:patchouli")
public class Tomes {
    public static final String MODID = "tomes";
    public static final String VERSION = "@VERSION@";
}
