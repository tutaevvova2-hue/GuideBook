import java.nio.file.*;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;

/**
 * Правка Patchouli: ссылка $(l:...) на закрытую статью больше не открывает её.
 * Подсказка «(Заблокировано)» остаётся, но клик ничего не делает.
 *
 * В BookTextParser обработчик клика — синтетический метод
 * lambda$null$N(Book, BookEntry, int, GuiBook), который создаёт GuiBookEntry.
 * В его начало вставляется: if (entry.isLocked()) return;
 *
 * Сборка и запуск (нужны asm-9.x.jar и asm-tree-9.x.jar):
 *   javac -cp asm.jar:asm-tree.jar LockedLinkPatch.java
 *   java -cp .:asm.jar:asm-tree.jar LockedLinkPatch BookTextParser.class BookTextParser.class
 * Готовый класс лежит в vendor/patchouli-overrides.
 */
public class LockedLinkPatch {
    static final String ENTRY = "vazkii/patchouli/client/book/BookEntry";
    static final String GUI_ENTRY = "vazkii/patchouli/client/book/gui/GuiBookEntry";

    public static void main(String[] args) throws Exception {
        ClassNode cn = new ClassNode();
        new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(cn, 0);
        int patched = 0;
        for (MethodNode m : cn.methods) {
            if (!m.name.startsWith("lambda$") || !m.desc.startsWith("(Lvazkii/patchouli/common/book/Book;L" + ENTRY + ";")) continue;
            boolean opens = false;
            for (AbstractInsnNode in : m.instructions.toArray())
                if (in instanceof TypeInsnNode && ((TypeInsnNode) in).desc.equals(GUI_ENTRY)) opens = true;
            if (!opens) continue;
            boolean isStatic = (m.access & Opcodes.ACC_STATIC) != 0;
            int slot = isStatic ? 1 : 2;
            InsnList pre = new InsnList();
            LabelNode go = new LabelNode();
            pre.add(new VarInsnNode(Opcodes.ALOAD, slot));
            pre.add(new MethodInsnNode(Opcodes.INVOKEVIRTUAL, ENTRY, "isLocked", "()Z", false));
            pre.add(new JumpInsnNode(Opcodes.IFEQ, go));
            pre.add(new InsnNode(Opcodes.RETURN));
            pre.add(go);
            pre.add(new FrameNode(Opcodes.F_SAME, 0, null, 0, null));
            m.instructions.insert(pre);
            patched++;
        }
        if (patched != 1) throw new IllegalStateException("ожидался один обработчик клика, найдено: " + patched);
        ClassWriter cw = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        cn.accept(cw);
        Files.write(Paths.get(args[1]), cw.toByteArray());
        System.out.println("ok");
    }
}
