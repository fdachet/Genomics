#Clustering
args <-   commandArgs(trailingOnly=TRUE)

COLOR_CHOICES <- c(
    "None"="none","Black"="black","White"="white","Red"="red","Dark   Red"="darkred",
    "Orange"="orange","Yellow"="yellow","Green"="green","Dark   Green"="darkgreen",
    "Blue"="blue","Dark   Blue"="darkblue","Cyan"="cyan","Turquoise"="turquoise",
    "Purple"="purple","Magenta"="magenta","Pink"="pink","Grey"="grey",
  "Light   Grey"="lightgrey","Brown"="brown","Gold"="gold","Navy"="navy",
    "Violet"="violet","Salmon"="salmon","Khaki"="khaki","Coral"="coral",
    "Chartreuse"="chartreuse","Steel   Blue"="steelblue","Sienna"="sienna",
    "Orchid"="orchid","Olive"="olivedrab","Sky   Blue"="skyblue",
    "Plum"="plum","Chocolate"="chocolate","Aquamarine"="aquamarine"
)

GROUP_COLOR_CHOICES <-   COLOR_CHOICES[COLOR_CHOICES!="none"]

DEFAULT_GROUP_COLORS <- c(
    "red","blue","green","orange","purple","cyan","magenta","darkgreen",
    "darkblue","pink","gold","turquoise","brown","steelblue","violet",
    "salmon","chartreuse","sienna","orchid","navy","coral","olivedrab",
    "skyblue","plum","chocolate","aquamarine","grey","khaki"
)

COLUMN_NORM_CHOICES <- c(
  "None"="none",
  "Column /   sum"="column_sum",
    "Z-score"="column_zscore",
  "Rank (1/n to   1)"="column_rank"
)

TRANSFORM_CHOICES <- c(
  "None"="none",
  "log10(1+x)"="log10p1",
  "sqrt(x)"="sqrt",
  "10^x"="pow10"
)

ROW_NORM_CHOICES <- c(
  "None"="none",
  "Row / sum"="row_sum",
  "Z-score"="row_zscore",
  "Rank (1/n to   1)"="row_rank"
)

DENDROGRAM_CHOICES <- c(
  "None"="none",
  "Genes"="row",
  "Samples"="column",
  "Genes +   Samples"="both"
)

DISTANCE_CHOICES <- c(
  "Pearson correlation   (1-r)"="pearson",
  "Spearman correlation   (1-rho)"="spearman",
    "Euclidean"="euclidean",
  "Manhattan"="manhattan"
)

LINKAGE_CHOICES <- c(
  "Average"="average",
  "Complete"="complete",
  "Ward D2"="ward.D2"
)

FORMAT_CHOICES <-   c("PNG"="png","PDF"="pdf","SVG"="svg")

rank_fraction <-   function(x) rank(x,ties.method="average")/length(x)

to_fraction <- function(x)   {
  x <- as.numeric(x)
  if (!is.finite(x)) stop("Percentage   must be numeric.")
  if (x>1) x <- x/100
  x
}

to_percent <- function(x)   {
  x <- as.numeric(x)
  if (x<=1) x <- x*100
  round(x)
}

choice_label <-   function(value,choices) {
  i <- match(value,unname(choices))
  if (is.na(i)) value else names(choices)[i]
}

default_group_colors <-   function(levels) {
  if (!length(levels)) return(character(0))
  x <-   rep(DEFAULT_GROUP_COLORS,length.out=length(levels))
  names(x) <- levels
  x
}

remembered_group_colors <-   function(levels,memory) {
  out <- default_group_colors(levels)
  if (!length(levels) || !length(memory))   return(out)
  hit <- intersect(levels,names(memory))
  if (length(hit)) out[hit] <- memory[hit]
  out
}

group_runs <- function(x)   {
  if (is.null(x) || !length(x))   return(data.frame())
  x <- as.character(x)
  r <- rle(x)
  ends <- cumsum(r$lengths)
  starts <- ends-r$lengths+1
    data.frame(value=r$values,start=starts,end=ends,middle=(starts+ends)/2,stringsAsFactors=FALSE)
}

read_tab_grid <-   function(path) {
  lines <-   readLines(path,warn=FALSE,encoding="UTF-8")
  if (!length(lines)) stop("Input file   is empty.")
  lines <-   sub("\r$","",lines)
  f <-   strsplit(lines,"\t",fixed=TRUE)
  nc <- max(lengths(f))
  g <-   matrix("",nrow=length(f),ncol=nc)
  for (i in seq_along(f))   g[i,seq_along(f[[i]])] <- f[[i]]
  g[1,1] <-   sub("^\ufeff","",g[1,1])
  ne <-   matrix(trimws(as.vector(g))!="",nrow=nrow(g),ncol=ncol(g))
    g[rowSums(ne)>0,colSums(ne)>0,drop=FALSE]
}

numeric_block <-   function(x) {
  v <- trimws(as.vector(x))
  if (!length(v) || any(v==""))   return(FALSE)
  n <- suppressWarnings(as.numeric(v))
  all(!is.na(n) & is.finite(n))
}

has_nonnumeric <-   function(x) {
  v <- trimws(as.vector(x))
  v <- v[v!=""]
  if (!length(v)) return(FALSE)
  n <- suppressWarnings(as.numeric(v))
  any(is.na(n))
}

grouping_candidate <-   function(g,row_group,column_group) {
  nr <- nrow(g); nc <- ncol(g)
  lc <- if (row_group) 2L else 1L
  hr <- if (column_group) 2L else 1L
  if (nc<=lc || nr<=hr) return(FALSE)
  dr <- seq.int(hr+1L,nr)
  dc <- seq.int(lc+1L,nc)
  if (!numeric_block(g[dr,dc,drop=FALSE]))   return(FALSE)
  if (row_group &&   !has_nonnumeric(g[dr,2])) return(FALSE)
  if (column_group &&   !has_nonnumeric(g[2,dc])) return(FALSE)
  TRUE
}

detect_grouping_structure   <- function(path) {
  g <- read_tab_grid(path)
  if (grouping_candidate(g,TRUE,TRUE))   return(list(row_group=TRUE,column_group=TRUE))
  if (grouping_candidate(g,TRUE,FALSE))   return(list(row_group=TRUE,column_group=FALSE))
  if (grouping_candidate(g,FALSE,TRUE))   return(list(row_group=FALSE,column_group=TRUE))
  if (grouping_candidate(g,FALSE,FALSE))   return(list(row_group=FALSE,column_group=FALSE))
  stop("The file structure could not be   interpreted automatically.")
}

read_expression_data <-   function(path,row_group=FALSE,column_group=FALSE) {
  if (!file.exists(path)) stop("Input   file does not exist: ",path)
  g <- read_tab_grid(path)
  lc <- if (row_group) 2L else 1L
  hr <- if (column_group) 2L else 1L
  if (ncol(g)<=lc) stop("No   expression columns were found.")
  if (nrow(g)<=hr) stop("No   expression rows were found.")
  dc <- seq.int(lc+1L,ncol(g))
  dr <- seq.int(hr+1L,nrow(g))

  if (column_group) {
    cg <- trimws(as.character(g[1,dc]))
    samples <-   trimws(as.character(g[2,dc]))
  } else {
    cg <- NULL
    samples <-   trimws(as.character(g[1,dc]))
  }

  if (row_group) {
    rg <- trimws(as.character(g[dr,1]))
    genes <- trimws(as.character(g[dr,2]))
  } else {
    rg <- NULL
    genes <- trimws(as.character(g[dr,1]))
  }

  if (any(is.na(genes)|genes==""))   stop("Empty gene names were detected.")
  if   (any(is.na(samples)|samples=="")) stop("Empty sample names   were detected.")
  if (row_group &&   any(is.na(rg)|rg=="")) stop("Empty row-group values were   detected.")
  if (column_group &&   any(is.na(cg)|cg=="")) stop("Empty column-group values were   detected.")

  genes <- make.unique(genes)
  samples <- make.unique(samples)
  txt <- g[dr,dc,drop=FALSE]
  values <-   suppressWarnings(as.numeric(txt))
  original <- trimws(as.vector(txt))
  bad <- is.na(values) &   original!=""

  if (any(bad)) {
    pos <-   which(matrix(bad,nrow=nrow(txt),ncol=ncol(txt)),arr.ind=TRUE)
    stop(paste0("Non-numeric expression   value '",txt[pos[1,1],pos[1,2]],"' at expression row   ",pos[1,1],", column ",pos[1,2],"."))
  }

  m <-   matrix(values,nrow=nrow(txt),ncol=ncol(txt))
  dimnames(m) <- list(genes,samples)
  storage.mode(m) <- "numeric"
  if (anyNA(m)) stop("Missing expression   values were detected.")
  if (!all(is.finite(m))) stop("Infinite   expression values were detected.")
  if (nrow(m)<2) stop("At least two   genes are required.")
  if (ncol(m)<1) stop("At least one   sample is required.")

  list(matrix=m,row_group=rg,column_group=cg)
}

normalize_columns <-   function(m,method) {
  if (method=="none") return(m)
  if (method=="column_sum") {
    s <- colSums(m)
      s[!is.finite(s)|abs(s)<.Machine$double.eps] <- 1
    return(sweep(m,2,s,"/"))
  }
  if (method=="column_zscore") {
    out <- scale(m)
    out[!is.finite(out)] <- 0
    dimnames(out) <- dimnames(m)
    return(out)
  }
  if (method=="column_rank") {
    out <- m
    for (j in seq_len(ncol(m))) out[,j] <-   rank_fraction(m[,j])
    return(out)
  }
  stop("Unknown column normalization:   ",method)
}

transform_matrix <-   function(m,method) {
  if (method=="none") return(m)
  if (method=="log10p1") {
    if (any(m<=-1)) stop("log10(1+x)   requires all values > -1.")
    return(log10(1+m))
  }
  if (method=="sqrt") {
    if (any(m<0)) stop("sqrt(x)   requires non-negative values.")
    return(sqrt(m))
  }
  if (method=="pow10") {
    out <- 10^m
    if (any(!is.finite(out))) stop("10^x   produced infinite values.")
    return(out)
  }
  stop("Unknown transformation:   ",method)
}

normalize_rows <-   function(m,method) {
  if (method=="none") return(m)
  if (method=="row_sum") {
    s <- rowSums(m)
      s[!is.finite(s)|abs(s)<.Machine$double.eps] <- 1
    return(sweep(m,1,s,"/"))
  }
  if (method=="row_zscore") {
    out <- t(scale(t(m)))
    out[!is.finite(out)] <- 0
    dimnames(out) <- dimnames(m)
    return(out)
  }
  if (method=="row_rank") {
    out <- m
    for (i in seq_len(nrow(m))) out[i,] <-   rank_fraction(m[i,])
    return(out)
  }
  stop("Unknown row normalization:   ",method)
}

prepare_matrix <-   function(m,settings) {
  m <-   normalize_columns(m,settings$column_norm)
  m <-   transform_matrix(m,settings$transformation)
  m <- normalize_rows(m,settings$row_norm)
  if (any(!is.finite(m)))   stop("Processing produced non-finite values.")
  m
}

make_distance <-   function(m,method) {
  if (method %in%   c("pearson","spearman")) {
    r <-   cor(t(m),method=method,use="pairwise.complete.obs")
    r[!is.finite(r)] <- 0
    diag(r) <- 1
    d <- 1-r
    d[d<0] <- 0
    return(as.dist(d))
  }
  dist(m,method=method)
}

make_dendrogram <-   function(m,distance_method,linkage_method) {
    as.dendrogram(hclust(make_distance(m,distance_method),method=linkage_method))
}

make_palette <-   function(low,medium,high,n=1000) {
  cols <- c(low,medium,high)
  cols <- cols[cols!="none"]
  if (length(cols)<2) stop("At least   two heatmap colors must be selected.")
  colorRampPalette(cols)(n)
}

make_breaks <-   function(m,n=1000) {
  x <- m[is.finite(m)]
  if (!length(x)) stop("No finite values   are available.")
  mn <- min(x); mx <- max(x)
  if (mn==mx) {
    p <- if (mn==0) 1 else abs(mn)*0.01
    return(seq(mn-p,mx+p,length.out=n+1))
  }
  if (mn<0 && mx>0) {
    z <- max(abs(c(mn,mx)))
    return(seq(-z,z,length.out=n+1))
  }
  seq(mn,mx,length.out=n+1)
}

format_scale_number <-   function(x,decimals=3) {
  decimals <- max(0,as.integer(decimals))
  if (abs(x)>=10000 ||   (abs(x)<10^(-max(1,decimals+2)) && x!=0))   return(formatC(x,format="e",digits=decimals))
    formatC(x,format="f",digits=decimals)
}

group_color_footer <-   function(title,color_map) {
  if (is.null(color_map)||!length(color_map))   return(NULL)
  paste0(title,":   ",paste(paste0(names(color_map),"=",unname(color_map)),collapse=",   "))
}

footer_font_size <-   function(settings) {
  fonts <-   c(settings$gene_font,settings$sample_font,settings$title_font,settings$key_font)
  if (isTRUE(settings$row_group_enabled)   && isTRUE(settings$show_row_group_names)) fonts <-   c(fonts,settings$row_group_font)
  if (isTRUE(settings$column_group_enabled)   && isTRUE(settings$show_column_group_names)) fonts <-   c(fonts,settings$column_group_font)
  fonts <- fonts[is.finite(fonts) &   fonts>0]
  if (!length(fonts)) return(0.7)
  min(fonts)
}

parameter_footer <-   function(settings) {
  p <- character(0)
  if (settings$column_norm!="none")   p <-   c(p,paste0("ColNorm=",choice_label(settings$column_norm,COLUMN_NORM_CHOICES)))
  if   (settings$transformation!="none") p <-   c(p,paste0("Transform=",choice_label(settings$transformation,TRANSFORM_CHOICES)))
  if (settings$row_norm!="none") p   <-   c(p,paste0("RowNorm=",choice_label(settings$row_norm,ROW_NORM_CHOICES)))

  if (settings$dendrogram!="none")   {
    p <- c(
      p,
        paste0("Dendro=",choice_label(settings$dendrogram,DENDROGRAM_CHOICES)),
        paste0("Dist=",choice_label(settings$distance,DISTANCE_CHOICES)),
        paste0("Link=",choice_label(settings$linkage,LINKAGE_CHOICES))
    )
  }

  if (settings$row_group_enabled) p <-   c(p,group_color_footer("RowGroups",settings$row_group_colors))
  if (settings$column_group_enabled) p <-   c(p,group_color_footer("ColumnGroups",settings$column_group_colors))

  if   (!identical(c(settings$low_color,settings$medium_color,settings$high_color),c("green","black","red")))   {
    z <-   c(settings$low_color,settings$medium_color,settings$high_color)
    z <- z[z!="none"]
    p <-   c(p,paste0("Colors=",paste(z,collapse="-")))
  }

  if (!settings$show_key) p <-   c(p,"IntensityScale=OFF")
  if (settings$key_decimals!=3) p <-   c(p,paste0("IntensityDecimals=",settings$key_decimals))

  if (to_percent(settings$key_width)!=33 ||   to_percent(settings$key_height)!=25) {
    p <-   c(p,paste0("ScaleSize=",to_percent(settings$key_width),"%x",to_percent(settings$key_height),"%"))
  }

  if (to_percent(settings$key_x)!=3 ||   to_percent(settings$key_y)!=3) {
    p <-   c(p,paste0("ScalePos=Right",to_percent(settings$key_x),"%/Down",to_percent(settings$key_y),"%"))
  }

  if (settings$key_font!=0.7) p <-   c(p,paste0("ScaleFont=",settings$key_font))
  if (settings$gene_font!=1) p <-   c(p,paste0("GeneFont=",settings$gene_font))
  if (settings$sample_font!=1) p <-   c(p,paste0("SampleFont=",settings$sample_font))
  if (settings$title_font!=1.2) p <-   c(p,paste0("TitleFont=",settings$title_font))
  if (!settings$show_genes) p <-   c(p,"GeneNames=OFF")
  if (!settings$show_samples) p <-   c(p,"SampleNames=OFF")

  if (settings$row_group_enabled &&   settings$show_row_group_names) p <-   c(p,paste0("RowGroupLabels=",settings$row_group_label_color,"/",settings$row_group_font))
  if (settings$column_group_enabled   && settings$show_column_group_names) p <-   c(p,paste0("ColumnGroupLabels=",settings$column_group_label_color,"/",settings$column_group_font))

  if (settings$sample_angle!=90) p <-   c(p,paste0("SampleAngle=",settings$sample_angle))
  if (settings$sample_area!=25) p <-   c(p,paste0("SampleArea=",settings$sample_area))
  if (settings$gene_area!=25) p <-   c(p,paste0("GeneArea=",settings$gene_area))

  if (!length(p)) return("Parameters:   defaults")
  paste0("Parameters:   ",paste(p,collapse=" | "))
}

draw_intensity_scale <-   function(palette,breaks,width_value,height_value,x_value,y_value,font_size,decimals)   {
  plot.new()
    plot.window(xlim=c(0,1),ylim=c(0,1),xaxs="i",yaxs="i")
  w <-   max(0.02,min(0.95,to_fraction(width_value)))
  h <-   max(0.02,min(0.90,to_fraction(height_value)))
  xo <-   max(0,min(0.90,to_fraction(x_value)))
  yo <-   max(0,min(0.90,to_fraction(y_value)))
  xl <- xo; yt <- 1-yo
  if (xl+w>0.98) w <- max(0.02,0.98-xl)
  if (yt-h<0.08) h <- max(0.02,yt-0.08)
  xr <- xl+w; yb <- yt-h
  edges <-   seq(xl,xr,length.out=length(palette)+1)

  for (i in seq_along(palette))   rect(edges[i],yb,edges[i+1],yt,col=palette[i],border=NA)
  rect(xl,yb,xr,yt,border="black")

  vmin <- min(breaks); vmax <-   max(breaks); vmid <- (vmin+vmax)/2
  ly <- max(0.015,yb-0.055); ty <-   min(0.995,yt+0.035)

    text(xl,ly,format_scale_number(vmin,decimals),adj=c(0,1),cex=font_size,xpd=NA)
    text((xl+xr)/2,ly,format_scale_number(vmid,decimals),adj=c(0.5,1),cex=font_size,xpd=NA)
    text(xr,ly,format_scale_number(vmax,decimals),adj=c(1,1),cex=font_size,xpd=NA)
    text((xl+xr)/2,ty,"Intensity",cex=font_size,font=2,xpd=NA)
}

draw_heatmap <-   function(matrix_input,settings,row_group=NULL,column_group=NULL) {
  m <-   prepare_matrix(matrix_input,settings)
  if (!is.null(row_group) &&   length(row_group)!=nrow(m)) stop("Row grouping length does not match   number of genes.")
  if (!is.null(column_group) &&   length(column_group)!=ncol(m)) stop("Column grouping length does not   match number of samples.")

  rd <- NULL; cd <- NULL

  if (settings$dendrogram %in%   c("row","both")) {
    rd <-   make_dendrogram(m,settings$distance,settings$linkage)
    ro <- order.dendrogram(rd)
  } else ro <- seq_len(nrow(m))

  if (settings$dendrogram %in%   c("column","both")) {
    cd <-   make_dendrogram(t(m),settings$distance,settings$linkage)
    co <- order.dendrogram(cd)
  } else co <- seq_len(ncol(m))

  m <- m[ro,co,drop=FALSE]
  if (!is.null(row_group)) row_group <-   row_group[ro]
  if (!is.null(column_group)) column_group   <- column_group[co]

  pal <-   make_palette(settings$low_color,settings$medium_color,settings$high_color)
  br <- make_breaks(m)

  rw <- if (settings$dendrogram %in% c("row","both")) 1.3 else 0.06
  ch <- if (settings$dendrogram %in% c("column","both")) 1.3 else 0.06
  ga <- max(0.5,settings$gene_area/10)
  sa <- max(0.5,settings$sample_area/10)

  # Width of the central heatmap panel.
  heatmap_width <- 5

  # Center of the heatmap matrix expressed as a fraction of the full
  # graphics-device width. This automatically compensates for the left
  # row-dendrogram area and the right gene-label area.
  title_adj <- (rw + heatmap_width / 2) / (rw + heatmap_width + ga)

  layout(
    rbind(c(0,3,0), c(2,1,5), c(0,4,6)),
    widths = c(rw, heatmap_width, ga),
    heights = c(ch, 5, sa)
  )
  par(oma=c(3.2,0.2,2.5,0.2))
  par(mar=c(0,0,0,0))

  image(
      x=seq_len(ncol(m)),y=seq_len(nrow(m)),z=t(m),
      col=pal,breaks=br,axes=FALSE,xlab="",ylab="",
      useRaster=TRUE,xaxs="i",yaxs="i"
  )
  box()

  par(mar=c(0,0,0,0))
  if (!is.null(rd))   plot(rd,horiz=TRUE,axes=FALSE,leaflab="none") else plot.new()

  par(mar=c(0,0,0,0))
  if (!is.null(cd))   plot(cd,axes=FALSE,leaflab="none") else plot.new()

  par(mar=c(0,0,0,0))
  plot.new()
    plot.window(xlim=c(0.5,ncol(m)+0.5),ylim=c(0,1),xaxs="i",yaxs="i")

  if (settings$column_group_enabled   && !is.null(column_group)) {
    gc <-   settings$column_group_colors[as.character(column_group)]
    gc[is.na(gc)] <- "grey"
      rect(seq_len(ncol(m))-0.5,0.87,seq_len(ncol(m))+0.5,0.97,col=unname(gc),border=NA)

    if   (isTRUE(settings$show_column_group_names)) {
      runs <- group_runs(column_group)
      if (nrow(runs)) for (i in   seq_len(nrow(runs))) {
          text(runs$middle[i],0.92,runs$value[i],cex=settings$column_group_font,col=settings$column_group_label_color,font=2,xpd=NA)
      }
    }
    sample_y <- 0.83
  } else sample_y <- 0.97

  if (settings$show_samples) {
    if (settings$sample_angle==0) {
        text(seq_len(ncol(m)),sample_y,labels=colnames(m),srt=0,adj=c(0.5,1),cex=settings$sample_font,xpd=NA)
    } else {
        text(seq_len(ncol(m)),sample_y,labels=colnames(m),srt=settings$sample_angle,adj=c(1,0.5),cex=settings$sample_font,xpd=NA)
    }
  }

  par(mar=c(0,0,0,0))
  plot.new()
    plot.window(xlim=c(0,1),ylim=c(0.5,nrow(m)+0.5),xaxs="i",yaxs="i")

  if (settings$row_group_enabled &&   !is.null(row_group)) {
    gc <-   settings$row_group_colors[as.character(row_group)]
    gc[is.na(gc)] <- "grey"
      rect(0.02,seq_len(nrow(m))-0.5,0.10,seq_len(nrow(m))+0.5,col=unname(gc),border=NA)

    if   (isTRUE(settings$show_row_group_names)) {
      runs <- group_runs(row_group)
      if (nrow(runs)) for (i in   seq_len(nrow(runs))) {
          text(0.06,runs$middle[i],runs$value[i],srt=90,cex=settings$row_group_font,col=settings$row_group_label_color,font=2,xpd=NA)
      }
    }
    gene_x <- 0.13
  } else gene_x <- 0.02

  if (settings$show_genes)   text(gene_x,seq_len(nrow(m)),labels=rownames(m),adj=c(0,0.5),cex=settings$gene_font,xpd=NA)

  par(mar=c(0,0,0,0))
  if (settings$show_key) {
    draw_intensity_scale(
        palette=pal,breaks=br,width_value=settings$key_width,height_value=settings$key_height,
        x_value=settings$key_x,y_value=settings$key_y,font_size=settings$key_font,decimals=settings$key_decimals
    )
  } else plot.new()

  if (!is.null(settings$title) &&   nzchar(settings$title)) {
      mtext(
      settings$title,
      side = 3,
      outer = TRUE,
      line = 0.5,
      cex = settings$title_font,
      font = 2,
      adj = title_adj
    )
  }

  footer <-   head(strwrap(parameter_footer(settings),width=120),3)
  footer_cex <- footer_font_size(settings)

  for (i in seq_along(footer)) {
      mtext(footer[i],side=1,outer=TRUE,line=0.35+(i-1)*0.70,cex=footer_cex,adj=0.5)
  }
}

clean_color <- function(x)   {
  if (x=="none") return(NULL)
    gsub("[^A-Za-z0-9]","",x)
}

make_filename <-   function(input_path,settings,width,height,format="png") {
  stem <-   tools::file_path_sans_ext(basename(input_path))

  ct <-   switch(settings$column_norm,none="C0",column_sum="CSum",column_zscore="CZ",column_rank="CRk")
  tt <-   switch(settings$transformation,none="T0",log10p1="TLog",sqrt="TSqrt",pow10="T10x")
  rt <-   switch(settings$row_norm,none="R0",row_sum="RSum",row_zscore="RZ",row_rank="RRk")
  dt <-   switch(settings$dendrogram,none="D0",row="DG",column="DS",both="DGS")
  dst <-   switch(settings$distance,pearson="Pear",spearman="Spear",euclidean="Euc",manhattan="Man")
  lt <-   switch(settings$linkage,average="Avg",complete="Comp",ward.D2="Ward")

  cols <-   unlist(Filter(Negate(is.null),list(clean_color(settings$low_color),clean_color(settings$medium_color),clean_color(settings$high_color))))
  tags <- c(ct,tt,rt,dt)
  if (settings$dendrogram!="none")   tags <- c(tags,dst,lt)
  if (settings$row_group_enabled) tags <-   c(tags,"RG")
  if (settings$column_group_enabled) tags   <- c(tags,"CG")

  size_tag <- if (format=="png")   paste0(width,"x",height) else   paste0("W",width,"xH",height)

  tags <- c(
    tags,
    paste(cols,collapse="-"),
      paste0("K",to_percent(settings$key_width),"x",to_percent(settings$key_height)),
      paste0("KP",to_percent(settings$key_x),"x",to_percent(settings$key_y)),
      paste0("KD",settings$key_decimals),
    toupper(format),
    size_tag
  )

    paste0(stem,"_HM_",paste(tags,collapse="_"),".",format)
}

unique_output_path <-   function(path) {
  if (!file.exists(path)) return(path)
  ext <- tools::file_ext(path)
  base <- tools::file_path_sans_ext(path)
  i <- 2
  repeat {
    p <-   paste0(base,"_",i,".",ext)
    if (!file.exists(p)) return(p)
    i <- i+1
  }
}

choose_local_file <-   function() {
  p <- tryCatch({
    if   (.Platform$OS.type=="windows") {
        utils::choose.files(default="*.*",caption="Select   tab-delimited expression matrix",multi=FALSE)
    } else {
      file.choose()
    }
  },error=function(e) NULL)

  if (is.null(p) || !length(p) || is.na(p[1])   || !nzchar(p[1])) return(NULL)
    normalizePath(p[1],winslash="/",mustWork=TRUE)
}

open_file_any <-   function(path) {
  if (!file.exists(path))   stop("Generated file does not exist.")
  if (.Platform$OS.type=="windows")   {
      shell.exec(normalizePath(path,winslash="\\\\",mustWork=TRUE))
  } else if   (Sys.info()[["sysname"]]=="Darwin") {
    system2("open",path,wait=FALSE)
  } else {
      system2("xdg-open",path,wait=FALSE)
  }
  invisible(NULL)
}

open_folder <-   function(path) {
  folder <- if (dir.exists(path)) path   else dirname(path)
  if (!dir.exists(folder)) stop("Output   folder does not exist: ",folder)
  if (.Platform$OS.type=="windows")   {
      shell.exec(normalizePath(folder,winslash="\\\\",mustWork=TRUE))
  } else if   (Sys.info()[["sysname"]]=="Darwin") {
      system2("open",folder,wait=FALSE)
  } else {
      system2("xdg-open",folder,wait=FALSE)
  }
  invisible(NULL)
}

parse_cli <-   function(args) {
  out <- list(); i <- 1
  while (i<=length(args)) {
    a <- args[i]
    if (a %in%   c("-h","--help")) { out$help <- TRUE; i <- i+1;   next }
    if (!startsWith(a,"--"))   stop("Unknown CLI argument: ",a)
    if (grepl("=",a,fixed=TRUE)) {
      p <-   strsplit(sub("^--","",a),"=",fixed=TRUE)[[1]]
      out[[p[1]]] <-   paste(p[-1],collapse="=")
      i <- i+1
      next
    }
    key <-   sub("^--","",a)
    if (i==length(args) ||   startsWith(args[i+1],"--")) {
      out[[key]] <- TRUE
      i <- i+1
    } else {
      out[[key]] <- args[i+1]
      i <- i+2
    }
  }
  out
}

as_bool <-   function(x,default=FALSE) {
  if (is.null(x)) return(default)
  if (is.logical(x)) return(x)
  x <- tolower(as.character(x))
  if (x %in%   c("true","t","1","yes","y"))   return(TRUE)
  if (x %in%   c("false","f","0","no","n"))   return(FALSE)
  stop("Invalid TRUE/FALSE value:   ",x)
}

parse_group_color_spec <-   function(specification,levels) {
  out <- default_group_colors(levels)
  if (is.null(specification) ||   !nzchar(specification)) return(out)
  p <-   trimws(strsplit(specification,";",fixed=TRUE)[[1]])
  if (all(grepl("=",p,fixed=TRUE)))   {
    for (x in p) {
      q <-   strsplit(x,"=",fixed=TRUE)[[1]]
      group <- trimws(q[1])
      color <-   trimws(paste(q[-1],collapse="="))
      if (group %in% levels) out[group] <-   color
    }
  } else {
    n <- min(length(p),length(levels))
    if (n>0) out[seq_len(n)] <-   p[seq_len(n)]
  }
  out
}

open_graphics_device <-   function(path,format,width,height,dpi=300) {
  format <- tolower(format)
  if (format=="png") {
      png(path,width=width,height=height,units="px",res=dpi)
    return(invisible(NULL))
  }
  if (format=="pdf") {
      pdf(path,width=width/72,height=height/72,useDingbats=FALSE,onefile=TRUE)
    return(invisible(NULL))
  }
  if (format=="svg") {
      svg(path,width=width/72,height=height/72,onefile=TRUE)
    return(invisible(NULL))
  }
  stop("Unknown output format:   ",format)
}

print_cli_help <-   function() {
  cat(c(
    "",
    "Heatmap.R",
    "",
    "GUI:",
    "    Rscript Heatmap.R",
    "",
    "CLI:",
    "    Rscript Heatmap.R --input FILE [OPTIONS]",
    "",
    "OUTPUT FORMAT:",
    "    --format png|pdf|svg",
    "",
    "GROUPING:",
    "    --row-group TRUE|FALSE",
    "    --column-group TRUE|FALSE",
    '    --row-group-colors "Tumor=red;Normal=blue"',
    '    --column-group-colors "Control=green;Disease=red"',
    "    --show-row-group-names TRUE|FALSE",
    "    --show-column-group-names TRUE|FALSE",
    "    --row-group-label-color black",
    "    --column-group-label-color black",
    "    --row-group-font 0.7",
    "    --column-group-font 0.7",
    "",
    "NORMALIZATION:",
    "    --column-norm none|column_sum|column_zscore|column_rank",
    "    --transform none|log10p1|sqrt|pow10",
    "    --row-norm none|row_sum|row_zscore|row_rank",
    "",
    "DENDROGRAM:",
    "    --dendrogram none|genes|samples|both",
    "    --distance pearson|spearman|euclidean|manhattan",
    "    --linkage average|complete|ward.D2",
    "",
    "INTENSITY:",
    "    --show-key TRUE",
    "    --key-width 33",
    "    --key-height 25",
    "    --key-x 3",
    "    --key-y 3",
    "    --key-font 0.7",
    "    --key-decimals 3",
    "",
    "LABELS:",
    "    --gene-font 1",
    "    --sample-font 1",
    "    --title-font 1.2",
    "    --show-genes TRUE",
    "    --show-samples TRUE",
    "    --sample-angle 90",
    "    --sample-area 25",
    "    --gene-area 25",
    '    --title "Gene Expression Heatmap"',
    "",
    "SIZE:",
    "    --width 5000",
    "    --height 8000",
    "    --dpi 300    (used for   PNG)",
    "",
    "OUTPUT:",
    "    --output FILE",
    "    --open TRUE",
    "    --open-folder TRUE",
    "",
    "WINDOWS POWERSHELL PNG:",
    'Rscript .\\\\Heatmap.R --input   "P:/data/Input.tabtxt" --format png --row-norm row_zscore   --dendrogram both --distance pearson --linkage average --width 5000 --height   8000 --dpi 300',
    "",
    "WINDOWS POWERSHELL SVG:",
    'Rscript .\\\\Heatmap.R --input   "P:/data/Input.tabtxt" --format svg --row-norm row_zscore   --dendrogram both --distance pearson --linkage average --width 5000 --height   8000',
    "",
    "WINDOWS POWERSHELL PDF:",
    'Rscript .\\\\Heatmap.R --input   "P:/data/Input.tabtxt" --format pdf --row-norm row_zscore   --dendrogram both --distance pearson --linkage average --width 5000 --height   8000',
    ""
  ),sep="\n")
}

run_cli <- function(args)   {
  opt <- parse_cli(args)
  if (isTRUE(opt$help)) { print_cli_help();   return(invisible(NULL)) }
  if (is.null(opt$input)) stop("--input   is required in CLI mode.")

  input_file <-   normalizePath(opt$input,winslash="/",mustWork=TRUE)
  detected <-   detect_grouping_structure(input_file)

  row_use <- if   (is.null(opt[["row-group"]])) detected$row_group else   as_bool(opt[["row-group"]],detected$row_group)
  column_use <- if   (is.null(opt[["column-group"]])) detected$column_group else   as_bool(opt[["column-group"]],detected$column_group)

  row_structure <- detected$row_group ||   row_use
  column_structure <-   detected$column_group || column_use

  dat <-   read_expression_data(input_file,row_group=row_structure,column_group=column_structure)

  rl <- if (row_use &&   !is.null(dat$row_group)) unique(as.character(dat$row_group)) else   character(0)
  cl <- if (column_use &&   !is.null(dat$column_group)) unique(as.character(dat$column_group)) else   character(0)

  rg_colors <-   parse_group_color_spec(opt[["row-group-colors"]],rl)
  cg_colors <-   parse_group_color_spec(opt[["column-group-colors"]],cl)

  dg <- if (is.null(opt$dendrogram))   "none" else tolower(opt$dendrogram)
  if (dg %in%   c("gene","genes","row")) dg <-   "row"
  if (dg %in%   c("sample","samples","column")) dg <-   "column"
  if (!dg %in%   c("none","row","column","both"))   stop("Invalid --dendrogram value: ",dg)

  out_format <- if (is.null(opt$format))   "png" else tolower(opt$format)
  if (!out_format %in%   c("png","pdf","svg")) stop("Invalid   --format. Use png, pdf, or svg.")

  settings <- list(
    column_norm=if   (is.null(opt[["column-norm"]])) "none" else   opt[["column-norm"]],
    transformation=if   (is.null(opt$transform)) "none" else opt$transform,
    row_norm=if   (is.null(opt[["row-norm"]])) "none" else   opt[["row-norm"]],
    dendrogram=dg,
    distance=if (is.null(opt$distance))   "pearson" else tolower(opt$distance),
    linkage=if (is.null(opt$linkage))   "average" else opt$linkage,
    low_color=if (is.null(opt$low))   "green" else opt$low,
    medium_color=if (is.null(opt$medium))   "black" else opt$medium,
    high_color=if (is.null(opt$high))   "red" else opt$high,
      show_key=as_bool(opt[["show-key"]],TRUE),
    key_width=if   (is.null(opt[["key-width"]])) 33 else   as.numeric(opt[["key-width"]]),
    key_height=if   (is.null(opt[["key-height"]])) 25 else   as.numeric(opt[["key-height"]]),
    key_x=if   (is.null(opt[["key-x"]])) 3 else   as.numeric(opt[["key-x"]]),
    key_y=if   (is.null(opt[["key-y"]])) 3 else   as.numeric(opt[["key-y"]]),
    key_font=if   (is.null(opt[["key-font"]])) 0.7 else   as.numeric(opt[["key-font"]]),
    key_decimals=if   (is.null(opt[["key-decimals"]])) 3 else   as.integer(opt[["key-decimals"]]),
    gene_font=if   (is.null(opt[["gene-font"]])) 1 else   as.numeric(opt[["gene-font"]]),
    sample_font=if   (is.null(opt[["sample-font"]])) 1 else   as.numeric(opt[["sample-font"]]),
    title_font=if   (is.null(opt[["title-font"]])) 1.2 else   as.numeric(opt[["title-font"]]),
      show_genes=as_bool(opt[["show-genes"]],TRUE),
      show_samples=as_bool(opt[["show-samples"]],TRUE),
    sample_angle=if   (is.null(opt[["sample-angle"]])) 90 else   as.numeric(opt[["sample-angle"]]),
    sample_area=if   (is.null(opt[["sample-area"]])) 25 else   as.numeric(opt[["sample-area"]]),
    gene_area=if   (is.null(opt[["gene-area"]])) 25 else   as.numeric(opt[["gene-area"]]),
    title=if (is.null(opt$title)) "Gene   Expression Heatmap" else opt$title,
    row_group_enabled=row_use,
    column_group_enabled=column_use,
    row_group_colors=rg_colors,
    column_group_colors=cg_colors,
      show_row_group_names=as_bool(opt[["show-row-group-names"]],FALSE),
      show_column_group_names=as_bool(opt[["show-column-group-names"]],FALSE),
    row_group_label_color=if   (is.null(opt[["row-group-label-color"]])) "black" else   opt[["row-group-label-color"]],
    column_group_label_color=if   (is.null(opt[["column-group-label-color"]])) "black" else   opt[["column-group-label-color"]],
    row_group_font=if   (is.null(opt[["row-group-font"]])) 0.7 else   as.numeric(opt[["row-group-font"]]),
    column_group_font=if   (is.null(opt[["column-group-font"]])) 0.7 else   as.numeric(opt[["column-group-font"]])
  )

  if (!settings$column_norm %in%   c("none","column_sum","column_zscore","column_rank"))   stop("Invalid --column-norm.")
  if (!settings$transformation %in%   c("none","log10p1","sqrt","pow10"))   stop("Invalid --transform.")
  if (!settings$row_norm %in%   c("none","row_sum","row_zscore","row_rank"))   stop("Invalid --row-norm.")
  if (!settings$distance %in%   c("pearson","spearman","euclidean","manhattan"))   stop("Invalid --distance.")
  if (!settings$linkage %in%   c("average","complete","ward.D2"))   stop("Invalid --linkage.")
  settings$key_decimals <-   max(0,settings$key_decimals)

  if (settings$linkage=="ward.D2"   && settings$dendrogram!="none" &&   settings$distance!="euclidean") warning("Ward D2 should   normally be used with Euclidean distance.")

  width <- if (is.null(opt$width)) 5000L   else as.integer(opt$width)
  height <- if (is.null(opt$height)) 8000L   else as.integer(opt$height)
  dpi <- if (is.null(opt$dpi)) 300L else   as.integer(opt$dpi)

  if (is.null(opt$output)) {
    output_file <-   unique_output_path(file.path(dirname(input_file),make_filename(input_file,settings,width,height,out_format)))
  } else {
    output_file <- opt$output
    if   (!grepl(paste0("\\\\.",out_format,"$"),output_file,ignore.case=TRUE))   output_file <- paste0(output_file,".",out_format)
    if (!dir.exists(dirname(output_file)))   dir.create(dirname(output_file),recursive=TRUE)
  }

    open_graphics_device(output_file,out_format,width,height,dpi)
    tryCatch(draw_heatmap(dat$matrix,settings,dat$row_group,dat$column_group),finally=dev.off())

  output_file <-   normalizePath(output_file,winslash="/",mustWork=TRUE)
  cat("\nHeatmap   created:\n",output_file,"\n\n",sep="")
  if (as_bool(opt$open,FALSE))   open_file_any(output_file)
  if   (as_bool(opt[["open-folder"]],FALSE))   open_folder(dirname(output_file))
  invisible(output_file)
}

run_gui <- function() {
  if   (!requireNamespace("shiny",quietly=TRUE)) stop('Install Shiny with:   install.packages("shiny")')
  library(shiny)
  options(shiny.maxRequestSize=500*1024^2)

  ui <- fluidPage(
    tags$head(tags$style(HTML("
      body{background:#f5f5f5}
      .panelbox{background:white;border:1px   solid #ccc;border-radius:7px;padding:12px;margin-bottom:12px}
        .sectiontitle{font-size:15px;font-weight:bold;border-bottom:1px solid   #ddd;padding-bottom:3px;margin-top:10px;margin-bottom:6px}
      .helpbox{background:#eef5ff;border:1px   solid #b9d1ec;border-radius:5px;font-size:12px;padding:8px;margin-bottom:8px}
        .warningbox{background:#fff3cd;border:1px solid   #e2c46e;border-radius:5px;font-size:12px;padding:8px;margin-bottom:8px}
        .pathbox{font-family:monospace;font-size:11px;word-break:break-all;margin-top:5px;margin-bottom:5px}
      .compact label{font-size:14px}
      .compact .form-group{margin-bottom:5px}
      .groupbox{border-left:3px solid   #ddd;padding-left:8px;margin-bottom:8px}
      .grouping-row   .checkbox{margin-top:5px;margin-bottom:5px}
      .grouping-row .checkbox   label{font-size:14px!important;font-weight:normal!important;white-space:nowrap}
      .grouping-row .checkbox label   span{font-size:14px!important}
      .keep-colors .checkbox   label{font-size:14px!important;font-weight:normal!important}
      .group-name-controls .checkbox   label{font-size:14px!important;font-weight:normal!important}
      .output-buttons   .btn{font-size:11px;padding:6px 3px;min-height:44px;white-space:normal}
    "))),

    titlePanel("Interactive Heatmap   Designer"),

    fluidRow(
      column(
        3,
        div(
          class="panelbox compact",
            div(class="sectiontitle","Input"),
            actionButton("select_file","Select Input   File",class="btn-primary",width="100%"),
            div(class="pathbox",textOutput("input_path")),

            div(class="sectiontitle","Preview"),
            numericInput("preview_genes","Random   genes",100,min=2,max=20000,step=10),

          fluidRow(
              column(6,checkboxInput("auto_redraw","Auto   redraw",FALSE)),
              column(6,actionButton("resample_genes","New   genes",width="100%"))
          ),

            actionButton("generate_preview","Generate / Redraw   Preview",class="btn-primary",width="100%"),

            div(class="sectiontitle","1. Column   normalization"),
            selectInput("column_norm",NULL,COLUMN_NORM_CHOICES,"none"),

            div(class="sectiontitle","2. Transformation"),
            selectInput("transformation",NULL,TRANSFORM_CHOICES,"none"),

            div(class="sectiontitle","3. Row normalization"),
            selectInput("row_norm",NULL,ROW_NORM_CHOICES,"none"),

            div(class="sectiontitle","Colors"),
          fluidRow(
              column(4,selectInput("high_color","HIGH",COLOR_CHOICES,"red")),
              column(4,selectInput("medium_color","MEDIUM",COLOR_CHOICES,"black")),
              column(4,selectInput("low_color","LOW",COLOR_CHOICES,"green"))
          ),

            div(class="sectiontitle","Intensity scale"),
          fluidRow(
              column(3,checkboxInput("show_key","Show",TRUE)),
              column(3,numericInput("key_width","Width   %",33,min=2,max=95)),
              column(3,numericInput("key_height","Height   %",25,min=2,max=90)),
              column(3,numericInput("key_decimals","Decimals",3,min=0,max=10,step=1))
          ),
          fluidRow(
              column(6,numericInput("key_x","Move right   %",3,min=0,max=90)),
              column(6,numericInput("key_y","Move down   %",3,min=0,max=90))
          ),

            div(class="sectiontitle","Labels / fonts"),
          fluidRow(
              column(3,numericInput("gene_font","Gene",1,min=0.1,max=5,step=0.1)),
              column(3,numericInput("sample_font","Sample",1,min=0.1,max=5,step=0.1)),
              column(3,numericInput("title_font","Title",1.2,min=0.1,max=5,step=0.1)),
              column(3,numericInput("key_font","Intensity",0.7,min=0.1,max=5,step=0.1))
          ),
          fluidRow(
              column(6,checkboxInput("show_genes","Gene   names",TRUE)),
              column(6,checkboxInput("show_samples","Sample   names",TRUE))
          ),
          fluidRow(
              column(4,numericInput("sample_angle","Name   angle",90,min=0,max=90,step=5)),
              column(4,numericInput("sample_area","Sample   area",25,min=5,max=100)),
              column(4,numericInput("gene_area","Gene   area",25,min=5,max=100))
          )
        )
      ),

      column(
        6,
        div(
          class="panelbox",
          h3("Heatmap Preview"),
          uiOutput("matrix_info"),
            plotOutput("heatmap_preview",height="850px")
        )
      ),

      column(
        3,
        div(
          class="panelbox compact",
            div(class="sectiontitle","Heatmap title"),
            textInput("title",NULL,"Gene Expression Heatmap"),

            div(class="sectiontitle","Grouping factors"),
          div(
            class="grouping-row",
            fluidRow(
                column(6,checkboxInput("row_group_enabled","Row   grouping",FALSE)),
                column(6,checkboxInput("column_group_enabled","Column   grouping",FALSE))
            )
          ),

            div(class="keep-colors",checkboxInput("keep_group_colors","Keep   group colors for new files",TRUE)),
            uiOutput("row_group_color_ui"),
            uiOutput("column_group_color_ui"),

            div(class="sectiontitle","Group names"),
          div(
              class="group-name-controls",
            fluidRow(
                column(6,checkboxInput("show_row_group_names","Row   names",FALSE)),
                column(6,checkboxInput("show_column_group_names","Column   names",FALSE))
            )
          ),

          fluidRow(
              column(6,selectInput("row_group_label_color","Row name   color",GROUP_COLOR_CHOICES,"black")),
              column(6,selectInput("column_group_label_color","Column   name color",GROUP_COLOR_CHOICES,"black"))
          ),

          fluidRow(
              column(6,numericInput("row_group_font","Row name   font",0.7,min=0.1,max=5,step=0.1)),
              column(6,numericInput("column_group_font","Column name   font",0.7,min=0.1,max=5,step=0.1))
          ),

            div(class="sectiontitle","Dendrogram"),
            selectInput("dendrogram","Cluster",DENDROGRAM_CHOICES,"none"),

          conditionalPanel(
            "input.dendrogram !=   'none'",
              selectInput("distance","Distance   metric",DISTANCE_CHOICES,"pearson"),
              uiOutput("distance_help"),
              selectInput("linkage","Clustering   algorithm",LINKAGE_CHOICES,"average"),
              uiOutput("linkage_help"),
              uiOutput("clustering_warning")
          )
        ),

        div(
          class="panelbox compact",
            div(class="sectiontitle","Output"),
          fluidRow(
              column(4,selectInput("output_format","Format",FORMAT_CHOICES,"png")),
              column(4,numericInput("png_width","Width   px",5000,min=500,max=30000,step=100)),
              column(4,numericInput("png_height","Height   px",8000,min=500,max=30000,step=100))
          ),
          fluidRow(
              column(4,numericInput("png_dpi","DPI",300,min=72,max=1200,step=50)),
              column(8,div(style="padding-top:27px;font-size:12px;","For   vector output, PDF/SVG are recommended."))
          ),

          div(
            class="output-buttons",
            fluidRow(
                column(4,actionButton("output_png","Output Heatmap to   File",class="btn-success",width="100%")),
                column(4,actionButton("open_png_button","Open Generated   File",class="btn-info",width="100%")),
                column(4,actionButton("open_folder_button","Open Output   Folder",width="100%"))
            )
          ),
            div(class="pathbox",uiOutput("generated_file_ui"))
        )
      )
    )
  )

  server <- function(input,output,session)   {
    input_path <- reactiveVal(NULL)
    detected_structure <-   reactiveVal(list(row_group=FALSE,column_group=FALSE))
    preview_indices <-   reactiveVal(integer(0))
    preview_state <- reactiveVal(NULL)
    generated_file <- reactiveVal(NULL)
    row_color_memory <-   reactiveVal(character(0))
    column_color_memory <-   reactiveVal(character(0))

    structure_flags <- reactive({
      detected <- detected_structure()
      list(
        row_group=detected$row_group ||   isTRUE(input$row_group_enabled),
        column_group=detected$column_group ||   isTRUE(input$column_group_enabled)
      )
    })

    parsed_data <- reactive({
      req(input_path())
      flags <- structure_flags()
        read_expression_data(input_path(),row_group=flags$row_group,column_group=flags$column_group)
    })

    save_color_memory <- function() {
      if   (!isTRUE(isolate(input$keep_group_colors))) return()
      if (is.null(isolate(input_path())))   return()
      d <-   tryCatch(isolate(parsed_data()),error=function(e) NULL)
      if (is.null(d)) return()

      if   (isTRUE(isolate(input$row_group_enabled)) && !is.null(d$row_group)) {
        lev <-   unique(as.character(d$row_group))
        mem <- isolate(row_color_memory())
        for (i in seq_along(lev)) {
          value <-   isolate(input[[paste0("row_group_color_",i)]])
          if (!is.null(value) &&   nzchar(value)) mem[lev[i]] <- value
        }
        row_color_memory(mem)
      }

      if   (isTRUE(isolate(input$column_group_enabled)) &&   !is.null(d$column_group)) {
        lev <-   unique(as.character(d$column_group))
        mem <-   isolate(column_color_memory())
        for (i in seq_along(lev)) {
          value <-   isolate(input[[paste0("column_group_color_",i)]])
          if (!is.null(value) &&   nzchar(value)) mem[lev[i]] <- value
        }
        column_color_memory(mem)
      }
    }

    observe({
      req(input_path())
      if (!isTRUE(input$keep_group_colors))   return()
      d <- parsed_data()

      if (isTRUE(input$row_group_enabled)   && !is.null(d$row_group)) {
        lev <-   unique(as.character(d$row_group))
        vals <-   vapply(seq_along(lev),function(i) {
          value <-   input[[paste0("row_group_color_",i)]]
          if (is.null(value)) NA_character_   else value
        },character(1))
        ok <- !is.na(vals) &   nzchar(vals)
        mem <- isolate(row_color_memory())
        if (any(ok)) {
          mem[lev[ok]] <- vals[ok]
          if   (!identical(mem,isolate(row_color_memory()))) row_color_memory(mem)
        }
      }

      if (isTRUE(input$column_group_enabled)   && !is.null(d$column_group)) {
        lev <-   unique(as.character(d$column_group))
        vals <-   vapply(seq_along(lev),function(i) {
          value <-   input[[paste0("column_group_color_",i)]]
          if (is.null(value)) NA_character_   else value
        },character(1))
        ok <- !is.na(vals) &   nzchar(vals)
        mem <-   isolate(column_color_memory())
        if (any(ok)) {
          mem[lev[ok]] <- vals[ok]
          if   (!identical(mem,isolate(column_color_memory()))) column_color_memory(mem)
        }
      }
    })

    observeEvent(input$select_file,{
      save_color_memory()
      p <- choose_local_file()
      if (is.null(p)) return()

      if   (!isTRUE(isolate(input$keep_group_colors))) {
        row_color_memory(character(0))
        column_color_memory(character(0))
      }

      detected <-   tryCatch(detect_grouping_structure(p),error=function(e) {
          showNotification(conditionMessage(e),type="error",duration=NULL)
        NULL
      })
      if (is.null(detected)) return()

      detected_structure(detected)
      input_path(p)

        updateCheckboxInput(session,"row_group_enabled",value=detected$row_group)
        updateCheckboxInput(session,"column_group_enabled",value=detected$column_group)

      preview_indices(integer(0))
      preview_state(NULL)
      generated_file(NULL)
    })

    output$input_path <- renderText({
      if (is.null(input_path())) "No   file selected" else input_path()
    })

    output$row_group_color_ui <-   renderUI({
      req(input_path())
      if (!isTRUE(input$row_group_enabled))   return(NULL)
      d <- parsed_data()
      if (is.null(d$row_group)) return(NULL)
      lev <-   unique(as.character(d$row_group))
      defs <- if   (isTRUE(input$keep_group_colors))   remembered_group_colors(lev,row_color_memory()) else   default_group_colors(lev)
        div(class="groupbox",tags$b("Row group   colors"),lapply(seq_along(lev),function(i) {
          selectInput(paste0("row_group_color_",i),lev[i],GROUP_COLOR_CHOICES,selected=unname(defs[i]))
      }))
    })

    output$column_group_color_ui <-   renderUI({
      req(input_path())
      if   (!isTRUE(input$column_group_enabled)) return(NULL)
      d <- parsed_data()
      if (is.null(d$column_group))   return(NULL)
      lev <-   unique(as.character(d$column_group))
      defs <- if   (isTRUE(input$keep_group_colors))   remembered_group_colors(lev,column_color_memory()) else   default_group_colors(lev)
        div(class="groupbox",tags$b("Column group   colors"),lapply(seq_along(lev),function(i) {
          selectInput(paste0("column_group_color_",i),lev[i],GROUP_COLOR_CHOICES,selected=unname(defs[i]))
      }))
    })

    get_current_group_colors <-   function(type,levels) {
      memory <- if (type=="row")   row_color_memory() else column_color_memory()
      defaults <- if   (isTRUE(input$keep_group_colors)) remembered_group_colors(levels,memory) else   default_group_colors(levels)
      if (!length(levels)) return(defaults)
      prefix <- if (type=="row")   "row_group_color_" else "column_group_color_"

      colors <-   vapply(seq_along(levels),function(i) {
        value <- input[[paste0(prefix,i)]]
        if (is.null(value) || !nzchar(value))   return(unname(defaults[i]))
        value
      },character(1))

      names(colors) <- levels
      colors
    }

    resample_preview <- function() {
      d <- parsed_data()
      n <-   min(max(2,as.integer(input$preview_genes)),nrow(d$matrix))
        preview_indices(sort(sample.int(nrow(d$matrix),n)))
    }

      observeEvent(list(input_path(),input$preview_genes,input$row_group_enabled,input$column_group_enabled),{
      req(input_path())
      resample_preview()
    },ignoreInit=TRUE)

    observeEvent(input$resample_genes,{
      req(input_path())
      resample_preview()
    })

    preview_data <- reactive({
      d <- parsed_data()
      idx <- preview_indices()
      if (!length(idx)) {
        resample_preview()
        idx <- preview_indices()
      }
      idx <- idx[idx<=nrow(d$matrix)]
        list(matrix=d$matrix[idx,,drop=FALSE],row_group=if   (is.null(d$row_group)) NULL else   d$row_group[idx],column_group=d$column_group)
    })

    current_settings <- reactive({
      d <- parsed_data()
      cols <-   c(input$low_color,input$medium_color,input$high_color)
        validate(need(sum(cols!="none")>=2,"Select at least   two heatmap colors."))

      rl <- if   (isTRUE(input$row_group_enabled) && !is.null(d$row_group))   unique(as.character(d$row_group)) else character(0)
      cl <- if   (isTRUE(input$column_group_enabled) && !is.null(d$column_group))   unique(as.character(d$column_group)) else character(0)

      list(
        column_norm=input$column_norm,
        transformation=input$transformation,
        row_norm=input$row_norm,
        dendrogram=input$dendrogram,
        distance=if (is.null(input$distance))   "pearson" else input$distance,
        linkage=if (is.null(input$linkage))   "average" else input$linkage,
        low_color=input$low_color,
        medium_color=input$medium_color,
        high_color=input$high_color,
        show_key=input$show_key,
        key_width=input$key_width,
        key_height=input$key_height,
        key_x=input$key_x,
        key_y=input$key_y,
        key_font=input$key_font,
          key_decimals=max(0,as.integer(input$key_decimals)),
        gene_font=input$gene_font,
        sample_font=input$sample_font,
        title_font=input$title_font,
        show_genes=input$show_genes,
        show_samples=input$show_samples,
        sample_angle=input$sample_angle,
        sample_area=input$sample_area,
        gene_area=input$gene_area,
        title=input$title,
          row_group_enabled=isTRUE(input$row_group_enabled),
          column_group_enabled=isTRUE(input$column_group_enabled),
          row_group_colors=get_current_group_colors("row",rl),
          column_group_colors=get_current_group_colors("column",cl),
          show_row_group_names=isTRUE(input$show_row_group_names),
          show_column_group_names=isTRUE(input$show_column_group_names),
          row_group_label_color=input$row_group_label_color,
          column_group_label_color=input$column_group_label_color,
        row_group_font=input$row_group_font,
          column_group_font=input$column_group_font
      )
    })

    observeEvent(input$generate_preview,{
      d <- preview_data()
        preview_state(list(matrix=d$matrix,row_group=d$row_group,column_group=d$column_group,settings=current_settings()))
    })

    observe({
        req(isTRUE(input$auto_redraw),input_path())
      d <- preview_data()
        preview_state(list(matrix=d$matrix,row_group=d$row_group,column_group=d$column_group,settings=current_settings()))
    })

    output$heatmap_preview <- renderPlot({
      s <- preview_state()
      validate(need(!is.null(s),"Press   'Generate / Redraw Preview'."))
        draw_heatmap(s$matrix,s$settings,s$row_group,s$column_group)
    },res=100)

    output$matrix_info <- renderUI({
      d <- parsed_data()
      txt <- paste0("Full matrix:   ",format(nrow(d$matrix),big.mark=",")," genes x   ",format(ncol(d$matrix),big.mark=",")," samples |   Preview: ",min(input$preview_genes,nrow(d$matrix))," genes")
      if (isTRUE(input$row_group_enabled)   && !is.null(d$row_group)) txt <- paste0(txt," | Row groups:   ",length(unique(d$row_group)))
      if (isTRUE(input$column_group_enabled)   && !is.null(d$column_group)) txt <- paste0(txt," | Column   groups: ",length(unique(d$column_group)))
      div(class="helpbox",txt)
    })

    output$distance_help <- renderUI({
      txt <- switch(
        input$distance,
        pearson="Pearson: groups   profiles with similar expression patterns regardless of absolute   magnitude.",
        spearman="Spearman: compares   relative ordering and is useful for ranked data or strong outliers.",
        euclidean="Euclidean: uses   absolute numerical distances. Recommended with Ward D2.",
        manhattan="Manhattan: uses   summed absolute differences and is less dominated by isolated extreme   differences."
      )
      div(class="helpbox",txt)
    })

    output$linkage_help <- renderUI({
      txt <- switch(
        input$linkage,
        average="Average linkage: useful   general-purpose choice for expression heatmaps.",
        complete="Complete linkage:   tends to create tighter and more separated clusters.",
        ward.D2="Ward D2: creates   compact variance-minimizing clusters and should use Euclidean distance."
      )
      div(class="helpbox",txt)
    })

    output$clustering_warning <-   renderUI({
      if (input$dendrogram!="none"   && input$linkage=="ward.D2" &&   input$distance!="euclidean") {
          div(class="warningbox",tags$b("Warning:   "),"Ward D2 should be used with Euclidean distance.")
      }
    })

    observeEvent(input$output_png,{
      state <- preview_state()
      if (is.null(state)) {
        showNotification("Generate a   preview first.",type="error")
        return()
      }

      save_color_memory()
      settings <- current_settings()
      flags <- structure_flags()

      full <-   read_expression_data(input_path(),row_group=flags$row_group,column_group=flags$column_group)
      fmt <- input$output_format

      filename <-   make_filename(input_path(),settings,input$png_width,input$png_height,fmt)
      path <-   unique_output_path(file.path(dirname(input_path()),filename))

      ok <- tryCatch({
          open_graphics_device(path,fmt,input$png_width,input$png_height,input$png_dpi)
          tryCatch(draw_heatmap(full$matrix,settings,full$row_group,full$column_group),finally=dev.off())
        TRUE
      },error=function(e) {
        showNotification(paste0("Heatmap   generation failed:   ",conditionMessage(e)),type="error",duration=NULL)
        FALSE
      })

      if (ok) {
          generated_file(normalizePath(path,winslash="/",mustWork=TRUE))
          showNotification(paste0(toupper(fmt)," created:   ",generated_file()),duration=8)
      }
    })

    output$generated_file_ui <- renderUI({
      p <- generated_file()
      if (is.null(p)) return("No file   generated yet.")
      tagList(tags$b("Generated   file:"),tags$br(),p)
    })

    observeEvent(input$open_png_button,{
      p <- generated_file()
      if (is.null(p) || !file.exists(p)) {
        showNotification("Generate the   file first.",type="error")
        return()
      }
        tryCatch(open_file_any(p),error=function(e)   showNotification(conditionMessage(e),type="error"))
    })

    observeEvent(input$open_folder_button,{
      req(input_path())
        tryCatch(open_folder(dirname(input_path())),error=function(e)   showNotification(conditionMessage(e),type="error"))
    })
  }

    runApp(shinyApp(ui=ui,server=server),launch.browser=TRUE)
}

if (length(args)==0) {
  run_gui()
} else {
  run_cli(args)
}
