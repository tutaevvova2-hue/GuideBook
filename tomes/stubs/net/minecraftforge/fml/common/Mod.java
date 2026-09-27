package net.minecraftforge.fml.common;

import java.lang.annotation.*;

// Заглушка аннотации Forge только для компиляции Tomes.java без Forge.
// В jar не попадает: в игре используется настоящая аннотация Forge.
@Retention(RetentionPolicy.RUNTIME)
@Target(ElementType.TYPE)
public @interface Mod {
    String modid();
    String name() default "";
    String version() default "";
    String dependencies() default "";
    String acceptedMinecraftVersions() default "";
}
