package demo;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;

/** A small processor: it does real file work so tests observe real effects. */
public final class Tool {
    private Tool() {}

    public static void main(String[] args) throws Exception {
        int index = 0;
        while (index < args.length) {
            String option = args[index];
            String first = index + 1 < args.length ? args[index + 1] : "";
            String second = index + 2 < args.length ? args[index + 2] : "";
            switch (option) {
                case "--print":
                    System.out.println(Helper.mark(first));
                    index += 2;
                    break;
                case "--require":
                    if (!Files.isRegularFile(Paths.get(first))) {
                        throw new IllegalStateException("missing " + first);
                    }
                    index += 2;
                    break;
                case "--copy":
                    Path copied = Paths.get(second).toAbsolutePath();
                    Files.createDirectories(copied.getParent());
                    Files.copy(Paths.get(first), copied, StandardCopyOption.REPLACE_EXISTING);
                    index += 3;
                    break;
                case "--write":
                    Path written = Paths.get(first).toAbsolutePath();
                    Files.createDirectories(written.getParent());
                    Files.write(written, second.getBytes("UTF-8"));
                    index += 3;
                    break;
                case "--sleep":
                    Thread.sleep(Long.parseLong(first));
                    index += 2;
                    break;
                case "--exit":
                    System.out.println(Helper.mark("failing"));
                    System.exit(Integer.parseInt(first));
                    break;
                default:
                    throw new IllegalArgumentException(option);
            }
        }
    }
}
